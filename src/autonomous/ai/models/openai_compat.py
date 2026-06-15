"""
OpenAI-compatible client for chat completions, embeddings, and audio
transcription. Designed to talk to Open WebUI, vLLM, LM Studio, and any
other server that implements the OpenAI HTTP shape — but the in-tree use
case is the Binghamton HPC at https://chat.binghamton.edu/api behind a VPN.

Image generation and TTS are intentionally not implemented; those route
to GeminiAIModel today (see BaseAgent.MODEL_REGISTRY).

When the endpoint is unreachable (VPN dropped, server sick, token revoked),
HPCUnreachableError is raised so the caller can surface a clear error to
the user instead of degrading silently.
"""

import io
import json

import requests

from autonomous import log
from autonomous.observability import counter, event
from autonomous.ai._json_utils import clean_json_response
from autonomous.ai.exceptions import (
    MALFORMED_2XX_EXCEPTIONS,
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
    MalformedResponseError,
)
from autonomous.config import settings
from autonomous.http import HttpClient, is_transport_failure as _http_is_transport_failure
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.taskrunner.autotasks import AutoTasks


class HPCUnreachableError(RuntimeError):
    """
    Raised when the HPC endpoint can't be reached. Distinct from
    server-side validation errors so the caller can map this to a 503
    + user-facing toast ("AI endpoint unreachable. Check the VPN.")
    rather than a generic 500.
    """


# Status codes that indicate transport/availability problems, not bad input.
# 401 is included because in this deployment a 401 means "token expired or
# revoked" — the user has to re-auth, same recovery path as a VPN drop.
# 5xx codes are checked via the range branch in ``_is_transport_failure``
# so the whole server-error family (including 500 — previously missing and
# the cause of issue #39's log flood — plus partner-CDN codes 521-529)
# routes through retry instead of escaping as raw ``requests.HTTPError``.
_TRANSPORT_FAILURE_CODES = frozenset({401})


def _is_transport_failure(status) -> bool:
    """True iff ``status`` is a transport-class failure eligible for retry.

    Used to translate HTTP responses into ``HPCUnreachableError`` so the
    ``retry()`` wrapper in ``_post`` (which catches that exception type)
    engages. Issue #39: the previous fixed-set check missed 500, so HPC
    500 responses bypassed retry entirely — every chunk in a degraded
    sync printed its own ``[HPC-UNREACHABLE]`` line.

    Robust to non-integer inputs: a ``MagicMock`` from a test fixture
    is neither in the set nor orderable against an int. Treating the
    type error as "not transport" preserves the old behavior of those
    tests (which relied on the fixed-set ``in`` check returning False
    against a MagicMock and falling through to ``raise_for_status``).

    Implementation delegates to ``autonomous.http.is_transport_failure``
    (#50 slice 2) — the predicate logic lives in one place so future
    transport-class refinements (e.g. opt-in 408/429 for throttle-aware
    callers) ship to every adapter via the central helper. The
    ``_TRANSPORT_FAILURE_CODES`` frozenset is passed as the extras set
    so the deployment-specific 401 == "VPN drop" equivalence stays
    here, not in the shared module.

    NOTE: as of #50 slice F this function is no longer called from
    ``_post`` — HttpClient runs the same predicate internally via the
    ``transport_failure_codes`` constructor kwarg. The function is
    retained for any external caller that imports it directly.
    """
    return _http_is_transport_failure(status, extra_codes=_TRANSPORT_FAILURE_CODES)


# Module-level HTTP client for the HPC POST path (#50 slice F).
#
# Pre-migration ``_post`` was a hand-rolled assembly of:
# - inner ``_attempt()`` closure calling ``_SESSION.post``
# - exception ladder for config-class errors (MissingSchema, InvalidURL,
#   SSLError, ProxyError, etc.) — re-raised raw to skip retry
# - ``except requests.RequestException`` → wrap into HPCUnreachableError
# - explicit ``_is_transport_failure(response.status_code)`` check →
#   wrap into HPCUnreachableError
# - explicit ``response.raise_for_status()``
# - outer ``retry(_attempt, max_attempts, sleep_seconds, catch=(HPCUnreachableError,))``
#
# HttpClient absorbs the entire pattern:
# - ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` covers most of the config-error
#   ladder (MissingSchema, InvalidURL, InvalidSchema, InvalidJSONError,
#   URLRequired, InvalidHeader, InvalidProxyURL) — re-raised raw.
# - ``transport_failure_codes=_TRANSPORT_FAILURE_CODES`` honours the 401
#   special-case; the 5xx range is automatic.
# - ``transport_error_cls=HPCUnreachableError`` makes HttpClient wrap
#   caught ``requests.RequestException`` and transport-class status
#   codes into HPCUnreachableError directly. The outer retry catches
#   ``transport_error_cls`` so HPCUnreachableError flows through the
#   retry budget as it did pre-migration.
# - ``max_attempts`` / ``retry_backoff`` from the same settings keys.
#
# **One behavior change from this migration, documented in MIGRATIONS.md:**
#
# HPCUnreachableError message format. HttpClient instantiates
# ``transport_error_cls`` with its own format strings:
#    - status-code raise: ``f"POST {url} returned {status}: {text[:200]}"``
#    - exception raise:   ``f"POST {url} failed ({type(exc).__name__}): {exc}"``
# Pre-migration the formats were:
#    - status:    ``f"HPC returned {status} for {path}: {text[:200]}"``
#    - exception: ``f"HPC unreachable ({type(exc).__name__}): {exc}"``
# The exception class is unchanged (HPCUnreachableError); only the
# embedded message string format differs. Log scrapers grepping the
# string need to widen the regex; ``except HPCUnreachableError``
# consumers are unaffected.
#
# Note: ``SSLError`` and ``ProxyError`` carve-out. Pre-migration the
# inner ``_attempt()`` ladder listed both as config-class (corporate
# cert-bundle / corporate-proxy misconfigs — retry can't fix and
# HPCUnreachable translation actively misdirects on-call). HttpClient's
# default ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` doesn't include them
# because for adapters over the public internet (fal.ai etc.) SSL/Proxy
# failures can legitimately be transient. We carry the carve-out
# forward by passing ``extra_non_transport_exceptions=`` to HttpClient
# so the per-deployment classification is preserved.
#
# **Why ContentDecodingError is deliberately NOT in the carve-out** (PR
# #99 decision, preserved here): malformed-gzip bodies can be transient
# server bugs, so the retry path is the safer default. Adding it to the
# carve-out would short-circuit retry for cases where retrying actually
# helps recover the call. A well-intentioned "let's just add all the
# requests.exceptions.* names" PR would silently regress this — the
# in-source breadcrumb is the second line of defense beyond
# ``test_unit_followup_iter_2026_05_17_pr107_followups.py``'s pin.
_HTTP = HttpClient(
    timeout=None,
    max_attempts=settings.hpc_retry_attempts,
    retry_backoff=settings.hpc_retry_backoff,
    transport_failure_codes=_TRANSPORT_FAILURE_CODES,
    transport_error_cls=HPCUnreachableError,
    extra_non_transport_exceptions=(
        requests.exceptions.SSLError,
        requests.exceptions.ProxyError,
    ),
)

# Module-level negative cache: (model, base_url) tuples known to NOT
# support strict-mode response_format. Populated on first conservative
# 400 detection. Cleared by _reset_unsupported_cache() (tests + manual
# operator override). Process-lifetime granularity is appropriate —
# servers gain strict-mode support via deploys, deploys typically
# accompany worker restarts.
_UNSUPPORTED_STRICT_MODE: set[tuple[str, str]] = set()

# Shared counter with local_model.py (#51 step 3). Idempotent on name
# via the observability registry — the first caller registers, the
# second returns the same singleton. Bumped on first detection per
# (model, endpoint) per process, matching the log emission's gate.
_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER = counter(
    "structured_outputs_unavailable_total",
    description=(
        "JSON adapters falling back from strict-mode schema enforcement "
        "(first detection per (model, endpoint) per process)"
    ),
    label_names=("provider",),
)

# Substrings that indicate a 4xx response was specifically about
# strict-mode unsupported-ness (rather than a real client bug like
# bad schema or bad model name). Conservative — only fall back on
# explicit signals to avoid masking real errors.
_STRICT_MODE_ERROR_MARKERS = (
    "json_schema",
    "response_format",
    "unsupported_parameter",
    "structured output",
)

# Phrases that indicate the SERVER supports strict mode but the caller's
# SCHEMA violates OpenAI's strict-output dialect (which is stricter than
# the JSON Schema meta-schema — requires additionalProperties:false,
# every property in required, no format/$ref, etc.). When matched, the
# heuristic returns False because caching the endpoint as unsupported
# would silently downgrade future calls against an endpoint that's
# actually working correctly. The right fix is for the caller to repair
# their schema, not for us to retry in loose mode. Tracks issue #28.
_STRICT_DIALECT_VIOLATION_MARKERS = (
    "invalid schema",
    "additionalproperties must be false",
    "missing required field",
    "must be in 'required'",
    "must be in `required`",
    "in 'required' array",
    "not allowed in strict",
    "invalid type for 'type'",
    "schema must be an object",
)


def _reset_unsupported_cache() -> None:
    """Clear the negative cache. Tests use this for isolation; operators
    use it after deploying a server-side fix to re-probe strict-mode
    support without restarting the worker."""
    _UNSUPPORTED_STRICT_MODE.clear()


def _looks_like_unsupported_strict_mode(status: int, body_text: str) -> bool:
    """Conservative heuristic: only flag responses whose body explicitly
    mentions strict-mode-specific terms. A bare 400 (real client bug,
    e.g. bad schema or bad model name) is intentionally NOT flagged —
    silently retrying in loose mode would mask the real error.

    Accepts 400 and 422 (some servers use 422 for validation rejections).

    Two-tier classification (issue #28):
      1. **Early reject on dialect-violation phrasings.** OpenAI strict
         mode rejects schemas that pass JSON Schema meta-validation but
         violate the strict-output dialect (additionalProperties:false,
         every property in required, no format/$ref). The error body
         mentions strict-mode terms — without this reject, the original
         markers would match and we'd cache the endpoint as unsupported
         when in fact it's working correctly and the caller's schema is
         broken.
      2. **Capability-marker fallback.** If the body doesn't match any
         dialect-violation phrasing, fall through to the existing
         broad-marker check. Non-OpenAI servers (HPC's Open WebUI proxy,
         vLLM, etc.) emit less-structured error bodies, so we keep the
         broad markers as a belt-and-suspenders for those.
    """
    if status not in (400, 422):
        return False
    body_lower = body_text.lower()

    # Tier 1: explicit signal that the server supports strict mode but
    # the schema is bad. Don't cache; let the 400 propagate as a real
    # error so the caller fixes their schema.
    if any(m in body_lower for m in _STRICT_DIALECT_VIOLATION_MARKERS):
        return False

    # Tier 2: capability-unsupported signal. Cache and fall back.
    return any(m in body_lower for m in _STRICT_MODE_ERROR_MARKERS)


# Endpoint paths appear at both the ``_post(...)`` call site and the
# ``endpoint=`` label on the MalformedResponseError raised for that path.
# Naming them once (issue #92) keeps the two in lockstep.
_CHAT_ENDPOINT = "/chat/completions"
_TRANSCRIPTION_ENDPOINT = "/audio/transcriptions"
_EMBEDDINGS_ENDPOINT = "/embeddings"


def _extract_or_malformed(response, endpoint, extractor):
    """Parse ``response.json()``, run ``extractor`` over it, and translate
    the malformed-2xx failure family into ``MalformedResponseError``.

    Centralizes the three near-identical try/except blocks in ``_chat``,
    ``get_embedding``, and ``generate_transcription`` (issue #92). The
    ``extractor`` callable keeps the per-endpoint walk
    (``body["choices"][0]...`` vs ``body["data"][0]...`` vs the
    transcription shape) at the call site, but the catch tuple
    (``MALFORMED_2XX_EXCEPTIONS``, issue #102), the
    ``MalformedResponseError`` construction, and the defensive
    ``response.text`` read (``from_response``, issue #90) live in one
    place — so the walk stays inside the protected block (an empty
    ``{"choices": []}`` still translates instead of leaking ``IndexError``)
    while the boilerplate is DRY.
    """
    try:
        return extractor(response.json())
    except MALFORMED_2XX_EXCEPTIONS as exc:
        raise MalformedResponseError.from_response(
            response,
            f"HPC {endpoint} endpoint returned a malformed 2xx body: {exc}",
            endpoint=endpoint,
        ) from exc


def _normalize_transcription_body(body):
    """Coerce an /audio/transcriptions 2xx body to the LocalAIModel-
    compatible ``{"text": str, "segments": list}`` shape (issue #88).

    ``dict.get(key, default)`` only fires ``default`` when the key is
    ABSENT — a server returning legal JSON ``{"text": null,
    "segments": null}`` (e.g. no content transcribed) would otherwise
    leak ``{"text": None, "segments": None}`` past the malformed-2xx
    catch (the body parses fine and ``.get`` doesn't raise), and a caller
    doing ``result["text"].strip()`` hits
    ``AttributeError: 'NoneType' object has no attribute 'strip'``.
    Normalizing null-or-wrong-type to the documented ``str`` / ``list``
    default keeps the contract honest. ``body.get`` against a non-dict
    body raises ``AttributeError`` — caught by ``_extract_or_malformed``
    and translated to ``MalformedResponseError``, same as before.
    """
    text = body.get("text")
    segments = body.get("segments")
    return {
        "text": text if isinstance(text, str) else "",
        "segments": segments if isinstance(segments, list) else [],
    }


class OpenAIClient(AutoModel):
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(default="You are a helpful AI.")
    description = StringAttr(default="OpenAI-compatible client (Open WebUI / HPC).")

    # Defaults reflect the chat.binghamton.edu Open WebUI inventory; override
    # via env per-deployment. Read from the central typed catalog
    # (autonomous.config) — guarded int parsing means a malformed
    # HPC_REQUEST_TIMEOUT falls back to the default instead of crashing import.
    _base_url = settings.hpc_api_base_url.rstrip("/")
    _api_key = settings.hpc_api_key
    _text_model = settings.hpc_text_model
    _json_model = settings.hpc_json_model
    _summary_model = settings.hpc_summary_model
    _embedding_model = settings.hpc_embedding_model
    _stt_model = settings.hpc_stt_model
    _timeout = settings.hpc_request_timeout
    # ``_retry_attempts`` and ``_retry_backoff`` (settings.hpc_retry_attempts /
    # settings.hpc_retry_backoff) used to live here as class attrs the
    # inner ``_post`` retry wrapper read. Post-#50-slice-F the retry
    # config lives on ``_HTTP`` at module scope (read from the same
    # settings keys at module load). Tests that previously did
    # ``monkeypatch.setattr(OpenAIClient, "_retry_attempts", 1)`` to
    # speed up retry tests should instead do
    # ``monkeypatch.setattr(_HTTP, "max_attempts", 1)`` (and
    # ``_HTTP.retry_backoff`` for the sleep interval).

    def _headers(self, content_type="application/json"):
        h = {"Authorization": f"Bearer {self._api_key}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _post(self, path, json_body=None, files=None, data=None):
        """
        Issue a POST to the HPC. Raises HPCUnreachableError on transport
        problems (connection refused, timeout, 401/5xx) so the caller can
        translate to a user-visible error. Other exceptions (non-JSON
        response body, invalid content from caller) propagate as-is.

        Post-#50-slice-F: the per-call exception ladder + retry assembly
        is delegated to ``_HTTP`` (an ``autonomous.http.HttpClient``).
        Config-error subclasses (MissingSchema, InvalidURL, etc.) are
        re-raised raw by HttpClient's ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS``
        path; transport-class failures (5xx + 401 + raised RequestException
        subclasses including SSLError/ProxyError post-migration) wrap into
        HPCUnreachableError and flow through the configured retry budget.
        See the module-level ``_HTTP`` block for the full rationale.
        """
        if not self._base_url:
            raise HPCUnreachableError(
                "HPC_API_BASE_URL is not configured; cannot reach AI endpoint."
            )

        url = f"{self._base_url}{path}"

        if files is not None:
            # multipart — let requests set Content-Type with boundary
            return _HTTP.post(
                url,
                headers=self._headers(content_type=None),
                files=files,
                data=data or {},
                timeout=self._timeout,
            )
        return _HTTP.post(
            url,
            headers=self._headers(),
            json=json_body,
            timeout=self._timeout,
        )

    # ---------------- chat completions ----------------

    def _chat(self, model, system, user, response_format=None, temperature=0.7):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if current_job := AutoTasks().get_current_task():
            current_job.meta(payload=payload)
        response = self._post(_CHAT_ENDPOINT, json_body=payload)
        # Malformed-200 translation (#76). HttpClient classifies >=500
        # and 401 as transport-class (raised as HPCUnreachableError,
        # already retried); other 4xx (400, 403, 404, ...) surface as
        # ``requests.HTTPError`` via ``raise_for_status`` and bubble
        # PAST this call — ``generate_json`` explicitly catches HTTPError
        # downstream. So the helper only needs to cover the malformed-
        # 2xx-body case: empty choices / missing keys (KeyError /
        # IndexError / TypeError) or a non-JSON 2xx body (ValueError,
        # which json.JSONDecodeError subclasses). The shared
        # ``_extract_or_malformed`` helper owns the catch tuple (#102),
        # the typed-exception construction, and the defensive
        # ``response.text`` read (#90); the walk below stays inside its
        # protected block.
        return _extract_or_malformed(
            response,
            _CHAT_ENDPOINT,
            lambda body: body["choices"][0]["message"]["content"],
        )

    def generate_text(
        self,
        message,
        additional_instructions="",
        uri="",
        context=None,
        temperature=0.7,
        evaluation=False,
    ):
        system = self.instructions
        if additional_instructions:
            system = f"{system}\n{additional_instructions}"
        user = message
        if context:
            user += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"{json.dumps(context, indent=2)}"
            )
        if uri:
            user += f"\nUse the following URI for reference: {uri}"
        return self._chat(self._text_model, system, user, temperature=temperature)

    def generate_json(
        self,
        message,
        system_prompt=None,
        uri="",
        context=None,
        temperature=0.7,
        evaluation=False,
        json_schema=None,
        schema_name="response",
    ):
        system = system_prompt or self.instructions
        system = system.rstrip(". ") + ".\nYour response MUST be a single valid JSON object."
        user = message
        if context:
            user += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"{json.dumps(context, indent=2)}"
            )
        if uri:
            user += f"\nUse the following URI for reference: {uri}"
        user += "\n\nRespond with ONLY a valid JSON object."

        # Build the response_format payload. Strict mode when:
        #   - caller passed a schema
        #   - this (model, endpoint) is not in the negative cache
        # Otherwise loose mode (preserved existing behavior).
        endpoint_key = (self._json_model, self._base_url)
        use_strict = (
            json_schema is not None
            and endpoint_key not in _UNSUPPORTED_STRICT_MODE
        )
        if use_strict:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}

        # ``_chat`` reaches into ``body["choices"][0]["message"]["content"]``
        # — a real prod outage shape is ``{"choices": []}`` or ``{}``,
        # which leaks KeyError/IndexError/TypeError raw. MIGRATIONS promises
        # EmptyResponseError for "Empty body, no candidates, missing keys",
        # so translate at the call site rather than let stdlib exceptions
        # escape past the typed-exception contract.
        try:
            raw = self._chat(
                self._json_model,
                system,
                user,
                response_format=response_format,
                temperature=temperature,
            )
        except requests.HTTPError as exc:
            # Detect "this endpoint doesn't support strict mode" specifically
            # and fall back to loose. Bare 4xx (real client bug) propagates.
            resp = exc.response
            should_fallback = (
                use_strict
                and resp is not None
                and _looks_like_unsupported_strict_mode(resp.status_code, resp.text)
            )
            if not should_fallback:
                raise
            # Cache before retry: even if loose-mode also fails, the
            # strict-mode-unsupported signal is still valid — a future
            # call to the same (model, endpoint) should go straight to
            # loose without re-probing. Do NOT move this .add() below
            # the retry branch; that would cause repeated probe failures.
            _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
            # Migrated to ``observability.event()`` (#51 step 3) —
            # preserves the ``[STRUCTURED-OUTPUTS-UNAVAILABLE]`` prefix
            # at line-start for grep-based scrapers; adds structured
            # fields for parser-based consumers.
            # print_to_stdout=False: the entry lands in
            # logs/current_run_error_log.log regardless. Avoiding stdout
            # keeps the marker from interleaving with structured loggers
            # in embedding environments (web request logs, JSON-emitting
            # workers). Operators grep the log file.
            event(
                "structured_outputs_unavailable",
                level="warning",
                marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
                print_to_stdout=False,
                provider="openai_compat",
                model=self._json_model,
                endpoint=self._base_url,
                status=resp.status_code,
                body_excerpt=resp.text[:200],
                detection="first",
                cached_for_process=True,
            )
            try:
                _STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.inc(provider="openai_compat")
            except Exception as exc:  # noqa: BLE001
                log(
                    f"[openai_compat] structured_outputs_unavailable_total "
                    f"counter inc failed: {exc!r}"
                )
            # Retry once with loose mode.
            try:
                raw = self._chat(
                    self._json_model,
                    system,
                    user,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
            except (MalformedResponseError, requests.HTTPError) as inner_exc:
                # MalformedResponseError = _chat's #76 translation of the
                # stdlib KeyError/IndexError/TypeError ladder. Preserve
                # generate_json's pre-#76 contract: a malformed body on
                # any chat call (strict OR loose) surfaces as
                # GenerateJSONEmptyResponseError to the generate_json
                # caller. HTTPError on the loose retry stays in the
                # "fallback retry hit a 4xx" diagnostic envelope.
                raise GenerateJSONEmptyResponseError(
                    f"HPC chat endpoint returned an error after fallback retry: {inner_exc}"
                ) from inner_exc
        except MalformedResponseError as exc:
            # Same pre-#76 contract preservation as the fallback catch
            # above, for the strict-mode (non-fallback) path.
            raise GenerateJSONEmptyResponseError(
                f"HPC chat endpoint returned a malformed body: {exc}"
            ) from exc
        if not raw or not raw.strip():
            raise GenerateJSONEmptyResponseError(
                "HPC chat endpoint returned an empty body for generate_json."
            )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            cleaned = clean_json_response(raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                # Symmetric with the HTTPError fallback above (issue #124):
                # a strict-mode request that returned HTTP 200 but whose
                # body fails BOTH ``json.loads(raw)`` and
                # ``json.loads(clean_json_response(raw))`` means the
                # server accepted the call but didn't honor the grammar
                # constraint (Open WebUI + Ollama on large schemas was
                # the in-prod trigger). The reliable recovery is loose
                # ``json_object`` mode, which is already known to work
                # on this backend. Cache before retry — even if the loose
                # retry also fails, the strict-mode-unsupported signal
                # is still valid for subsequent calls.
                if use_strict:
                    _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
                    event(
                        "structured_outputs_unavailable",
                        level="warning",
                        marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
                        print_to_stdout=False,
                        provider="openai_compat",
                        model=self._json_model,
                        endpoint=self._base_url,
                        status=200,
                        body_excerpt=raw[:200],
                        detection="parse_failure_200",
                        cached_for_process=True,
                    )
                    try:
                        _STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.inc(provider="openai_compat")
                    except Exception as counter_exc:  # noqa: BLE001
                        log(
                            f"[openai_compat] structured_outputs_unavailable_total "
                            f"counter inc failed: {counter_exc!r}"
                        )
                    try:
                        loose_raw = self._chat(
                            self._json_model,
                            system,
                            user,
                            response_format={"type": "json_object"},
                            temperature=temperature,
                        )
                    except (MalformedResponseError, requests.HTTPError) as inner_exc:
                        raise GenerateJSONEmptyResponseError(
                            f"HPC chat endpoint returned an error after parse-failure fallback: {inner_exc}"
                        ) from inner_exc
                    if loose_raw and loose_raw.strip():
                        try:
                            return json.loads(loose_raw)
                        except json.JSONDecodeError:
                            try:
                                return json.loads(clean_json_response(loose_raw))
                            except json.JSONDecodeError:
                                # Loose retry also unparseable; fall through
                                # to the original ``GenerateJSONParseError``
                                # with the strict-mode raw body so the
                                # diagnostic reflects what the caller asked
                                # for.
                                pass
                log(
                    f"==== HPC JSON parse failure: {exc} ====\n"
                    f"--- RAW ---\n{raw[:500]}",
                    _print=True,
                )
                raise GenerateJSONParseError(
                    f"Could not parse JSON from HPC chat response: {exc}",
                    raw=raw,
                ) from exc

    def summarize_text(self, text, primer=""):
        primer = primer or "Summarize the following text concisely."
        # OpenAI-compatible endpoints don't need the chunk-by-context-window
        # dance Ollama did; modern models handle 32k+ context comfortably.
        return self._chat(self._summary_model, primer, text, temperature=0.5)

    # ---------------- transcription ----------------

    def generate_transcription(self, audio_file, prompt="", **kwargs):
        """
        OpenAI-compatible /audio/transcriptions. Returns the same
        ``{"text": ..., "segments": [...]}`` shape LocalAIModel returns,
        so callers (audioagent.py screenplay post-processing) work
        unchanged regardless of provider.

        Exception contract: 4xx responses propagate as
        ``requests.HTTPError`` (raised by HttpClient's
        ``raise_for_status``); only malformed 2xx bodies translate to
        ``MalformedResponseError`` (issue #82). Consumers that want a
        single typed-exception surface should catch both.
        """
        f_obj = io.BytesIO(audio_file) if isinstance(audio_file, bytes) else audio_file
        files = {"file": ("audio.opus", f_obj, "audio/ogg")}
        data = {
            "model": self._stt_model,
            "response_format": "verbose_json",  # asks for segments[] in response
        }
        if prompt:
            data["prompt"] = prompt

        if current_job := AutoTasks().get_current_task():
            current_job.meta(data=data)

        response = self._post(_TRANSCRIPTION_ENDPOINT, files=files, data=data)
        # Malformed-2xx translation (#82) — same family as the #76
        # _chat / get_embedding fixes, now via the shared
        # ``_extract_or_malformed`` helper (#92). The extractor enforces
        # the LocalAIModel-compatible ``{"text": str, "segments": list}``
        # shape even when the server returns the simpler "text" form.
        return _extract_or_malformed(
            response,
            _TRANSCRIPTION_ENDPOINT,
            _normalize_transcription_body,
        )

    # ---------------- embeddings ----------------

    def get_embedding(self, text):
        """Returns a list of floats (length depends on the configured embedding model).

        Raises ``MalformedResponseError`` if the 2xx body lacks the
        expected ``data[0].embedding`` shape (issue #76 — was previously
        a leaked stdlib KeyError/IndexError/TypeError).
        """
        payload = {"model": self._embedding_model, "input": text}
        response = self._post(_EMBEDDINGS_ENDPOINT, json_body=payload)
        return _extract_or_malformed(
            response,
            _EMBEDDINGS_ENDPOINT,
            lambda body: body["data"][0]["embedding"],
        )

    # ---------------- not implemented (route via gemini) ----------------

    def generate_image(self, *args, **kwargs):
        raise NotImplementedError(
            "OpenAIClient does not implement image generation. "
            "Set IMAGE_AI_AGENT=gemini (or =local) to route around it."
        )

    def upscale_image(self, *args, **kwargs):
        raise NotImplementedError(
            "OpenAIClient does not implement image upscaling. "
            "Set IMAGE_AI_AGENT=gemini (or =local) to route around it."
        )

    def generate_audio(self, *args, **kwargs):
        raise NotImplementedError(
            "OpenAIClient does not implement TTS. "
            "Set TTS_AI_AGENT=gemini (or =local) to route around it."
        )
