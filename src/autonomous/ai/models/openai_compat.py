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
import os

import requests

from autonomous import log
from autonomous.ai._json_utils import clean_json_response
from autonomous.ai.exceptions import (
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
)
from autonomous.ai.retry import retry
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.taskrunner.autotasks import AutoTasks

# Module-level Session pools connections; concurrent calls are safe but
# Session-state mutation (headers/cookies/auth) from a sibling thread
# is not — every call site here uses per-request `headers=` kwargs.
_SESSION = requests.Session()


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
_TRANSPORT_FAILURE_CODES = frozenset({401, 502, 503, 504})

# Module-level negative cache: (model, base_url) tuples known to NOT
# support strict-mode response_format. Populated on first conservative
# 400 detection. Cleared by _reset_unsupported_cache() (tests + manual
# operator override). Process-lifetime granularity is appropriate —
# servers gain strict-mode support via deploys, deploys typically
# accompany worker restarts.
_UNSUPPORTED_STRICT_MODE: set[tuple[str, str]] = set()

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
    """
    if status not in (400, 422):
        return False
    body_lower = body_text.lower()
    return any(m in body_lower for m in _STRICT_MODE_ERROR_MARKERS)


class OpenAIClient(AutoModel):
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(default="You are a helpful AI.")
    description = StringAttr(default="OpenAI-compatible client (Open WebUI / HPC).")

    # Defaults reflect the chat.binghamton.edu Open WebUI inventory; override
    # via env per-deployment. Any value here just keeps construction working
    # if the env vars are unset (tests, packaging build).
    _base_url = os.environ.get("HPC_API_BASE_URL", "").rstrip("/")
    _api_key = os.environ.get("HPC_API_KEY", "")
    _text_model = os.environ.get("HPC_TEXT_MODEL", "gpt-oss:20b")
    _json_model = os.environ.get("HPC_JSON_MODEL", _text_model)
    _summary_model = os.environ.get("HPC_SUMMARY_MODEL", "gemma4:26b")
    _embedding_model = os.environ.get(
        "HPC_EMBEDDING_MODEL", "dengcao/Qwen3-Embedding-8B:F16"
    )
    _stt_model = os.environ.get("HPC_STT_MODEL", "whisper-1")
    _timeout = int(os.environ.get("HPC_REQUEST_TIMEOUT", 120))
    _retry_attempts = int(os.environ.get("HPC_RETRY_ATTEMPTS", 3))
    _retry_backoff = int(os.environ.get("HPC_RETRY_BACKOFF", 10))

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
        """
        if not self._base_url:
            raise HPCUnreachableError(
                "HPC_API_BASE_URL is not configured; cannot reach AI endpoint."
            )

        url = f"{self._base_url}{path}"

        def _attempt():
            try:
                if files is not None:
                    # multipart — let requests set Content-Type with boundary
                    response = _SESSION.post(
                        url,
                        headers=self._headers(content_type=None),
                        files=files,
                        data=data or {},
                        timeout=self._timeout,
                    )
                else:
                    response = _SESSION.post(
                        url,
                        headers=self._headers(),
                        json=json_body,
                        timeout=self._timeout,
                    )
            except (
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidURL,
                requests.exceptions.InvalidSchema,
                requests.exceptions.InvalidJSONError,
                requests.exceptions.URLRequired,
                requests.exceptions.InvalidHeader,
                requests.exceptions.InvalidProxyURL,
                requests.exceptions.SSLError,
                requests.exceptions.ProxyError,
            ):
                # Config / programmer errors — propagate raw rather
                # than burn retry against unfixable causes. Must come
                # before the broader catch below.
                #
                # ContentDecodingError is deliberately NOT in this tuple:
                # malformed-gzip bodies can be transient server bugs, so
                # retry is the safer default. A test in the followup
                # suite pins the exclusion.
                raise
            except requests.RequestException as exc:
                # Catch the documented base so transient transport
                # errors (RetryError, ChunkedEncodingError, future
                # subclasses) flow through the HPCUnreachableError
                # translation and the [HPC-UNREACHABLE] scrape sentinel.
                raise HPCUnreachableError(
                    f"HPC unreachable ({type(exc).__name__}): {exc}"
                ) from exc

            if response.status_code in _TRANSPORT_FAILURE_CODES:
                raise HPCUnreachableError(
                    f"HPC returned {response.status_code} for {path}: "
                    f"{response.text[:200]}"
                )
            response.raise_for_status()
            return response

        return retry(
            _attempt,
            max_attempts=self._retry_attempts,
            sleep_seconds=self._retry_backoff,
            catch=(HPCUnreachableError,),
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
        response = self._post("/chat/completions", json_body=payload)
        body = response.json()
        return body["choices"][0]["message"]["content"]

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
            _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
            log(
                f"[STRUCTURED-OUTPUTS-UNAVAILABLE] First detection: "
                f"model={self._json_model} endpoint={self._base_url} "
                f"status={resp.status_code} body_excerpt={resp.text[:200]!r} "
                f"(cached for this process)",
                _print=True,
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
            except (KeyError, IndexError, TypeError) as inner_exc:
                raise GenerateJSONEmptyResponseError(
                    f"HPC chat endpoint returned a malformed body after fallback: {inner_exc}"
                ) from inner_exc
        except (KeyError, IndexError, TypeError) as exc:
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

        response = self._post("/audio/transcriptions", files=files, data=data)
        body = response.json()
        # Ensure the LocalAIModel-compatible shape even if the server
        # returns the simpler "text" form.
        return {
            "text": body.get("text", ""),
            "segments": body.get("segments", []),
        }

    # ---------------- embeddings ----------------

    def get_embedding(self, text):
        """Returns a list of floats (length depends on the configured embedding model)."""
        payload = {"model": self._embedding_model, "input": text}
        response = self._post("/embeddings", json_body=payload)
        body = response.json()
        return body["data"][0]["embedding"]

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
