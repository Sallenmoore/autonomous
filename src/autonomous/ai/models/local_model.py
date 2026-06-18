import io
import json
import random
import time

import requests
from pydub import AudioSegment
from pydub.exceptions import PydubException

from autonomous import log
from autonomous.ai._extract import extract_or_malformed
from autonomous.ai._json_messages import (
    STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER as _STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER,
    build_chat_json_messages,
)
from autonomous.ai._json_utils import clean_json_response
from autonomous.observability import event
from autonomous.ai.exceptions import (
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
    MalformedResponseError,
)
from autonomous.ai.retry import retry
from autonomous.config import env_str, settings
from autonomous.http import HttpClient
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.taskrunner.autotasks import AutoTasks

# Module-level HTTP client for Ollama + media_ai calls (#50 slice C, README #16).
# Pre-migration this was a bare ``_SESSION = requests.Session()`` with each
# call site invoking ``_SESSION.post`` directly. The Session-pooling
# behaviour is preserved (HttpClient holds its own requests.Session
# internally), and the migration sets the architectural foundation for
# README #16 (adding retry on local_model HTTP calls).
#
# Concurrency note: ``requests.Session.post`` is safe to call from
# multiple threads concurrently. What is NOT safe is mutating
# Session-level state (``_HTTP.session.headers``, ``.cookies``, ``.auth``)
# from one thread while another is mid-request. This module's call sites
# pass all per-call state via kwargs (no Session-level mutation), so the
# concurrent-POST workload is fine. PR #76 review comment r3250218127
# flagged the prior overstatement; clarified per #78 follow-up.
#
# Defaults:
# - ``timeout=None``: every call site already passes a per-call ``timeout=``
#   kwarg (the ``self._text_timeout`` / ``_summary_timeout`` /
#   ``_media_timeout`` / hardcoded-30 family). ``None`` lets the per-call
#   override govern without imposing an additional cap.
# - ``max_attempts=1``: preserves pre-migration no-retry behaviour. README
#   #16 (adding retry) is deferred to a follow-up slice because retry
#   policy varies per call site (text generation shouldn't retry — the
#   model has already burned through tokens; media uploads might) and
#   ``HttpClient.max_attempts`` is client-level, not per-call. The right
#   shape is either two clients (retry-enabled for idempotent uploads,
#   no-retry for generation) or per-call ``request()`` overrides.
#
# Tests can monkeypatch ``autonomous.ai.models.local_model._HTTP``
# (or ``_HTTP.post`` / ``_HTTP.get``) to a stub. The pre-migration
# ``_SESSION`` patch target is intentionally NOT preserved as an
# alias: HttpClient routes through ``session.request("POST", ...)``
# rather than ``session.post(...)``, so a stale ``_SESSION.post``
# monkeypatch would silently fail to intercept the migrated call.
# An honest break beats a misleading alias — the lone known consumer
# (tests/unit/test_unit_http_session_pooling.py) is updated in the
# same PR as this migration.
#
# ``transport_error_cls=requests.ConnectionError`` (mirrors flux #85).
# Must stay inside the ``requests.RequestException`` family so the
# ``except requests.RequestException`` catch in ``flush_memory`` keeps
# matching; the default ``TransportError`` (``RuntimeError`` subclass)
# would bypass it. Pinning the wrap to the *base* ``RequestException``
# (the pre-#97 choice) silently broke the outer ``retry()`` in
# ``generate_json`` once its catch tuple was narrowed in the same
# cycle: a base ``RequestException(msg)`` instance is not a
# ``ConnectionError`` / ``Timeout`` subclass instance, so real
# transient transport failures dropped from 3 attempts to 1. Cost
# of the narrower wrap: a real ``Timeout`` reaches callers as a
# ``ConnectionError`` instance, type-erased. Same trade flux took.
_HTTP = HttpClient(
    timeout=None,
    max_attempts=1,
    transport_error_cls=requests.ConnectionError,
)

# Module-level cache of (model, endpoint) combos we've already logged
# the "no structured outputs support" marker for. Avoids log spam on
# every JSON call. Cleared by process restart only.
_STRUCTURED_OUTPUTS_LOGGED: set[tuple[str, str]] = set()


class LocalAIModel(AutoModel):
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(default="You are a helpful AI.")
    description = StringAttr(default="A Local AI Model using Ollama and Media AI.")

    # Config — read from the central typed catalog (autonomous.config).
    # URLs are rstrip'd so path joins produce "<url>/<path>" not "<url>//<path>";
    # guarded int parsing means a malformed timeout falls back to the default
    # instead of crashing import.
    _ollama_url = settings.ollama_api_base_url.rstrip("/")
    _media_url = settings.media_api_base_url.rstrip("/")
    _audio_url = settings.media_audio_api_base_url.rstrip("/")
    _image_url = settings.media_image_api_base_url.rstrip("/")
    _text_model = settings.ollama_model
    _context_limit = settings.ollama_context_limit

    # Timeouts (seconds) — CPU-only Ollama is slow; these prevent indefinite hangs
    _retry_sleep = settings.ollama_retry_sleep       # sleep between JSON retries
    _json_timeout = settings.ollama_json_timeout     # 20 min
    _text_timeout = settings.ollama_text_timeout     # 15 min
    _summary_timeout = settings.ollama_summary_timeout   # 10 min/chunk
    _media_timeout = settings.media_request_timeout  # 5 min

    def _convert_tools_to_json_schema(self, user_function):
        schema = {
            "name": user_function.get("name"),
            "description": user_function.get("description", ""),
            "parameters": user_function.get("parameters", {}),
        }
        return json.dumps(schema, indent=2)

    def _clean_json_response(self, text):
        return clean_json_response(text)

    def _evaluate_response(self, instruction, content, goal):
        eval_prompt = {
            # Read live (not via the settings snapshot) so an OLLAMA_TEXT_MODEL
            # flip lands without a restart — mirrors the original os.environ.get
            # at this call site. Do not switch to settings.ollama_text_model.
            "model": env_str("OLLAMA_TEXT_MODEL", "gemma4:26b"),
            "messages": [
                {
                    "role": "user",
                    "content": f"Evaluate the original instruction and goal in regards to the output produced.\n\nGoal: {goal}\nInstruction: {instruction}\n\nOutput:\n{content}\n\n Write an improved prompt that will get the output closer to the stated goal. Only output the complete improved prompt. Do not preface it with any message.",
                }
            ],
            "stream": False,
        }
        res_eval = _HTTP.post(f"{self._ollama_url}/api/chat", json=eval_prompt, timeout=self._text_timeout)

        return res_eval.json().get("message", {}).get("content", "")

    def flush_memory(self, model_name):
        """Forces Ollama to immediately unload the model from system RAM."""
        log(f"Flushing {model_name} from memory to free resources...", _print=True)
        try:
            # Sending keep_alive=0 triggers an immediate VRAM/RAM eviction
            _HTTP.post(
                f"{self._ollama_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30,
            )
        except requests.RequestException as e:
            log(f"Failed to flush memory: {e}", _print=True)

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
        # The local Ollama path has no equivalent of OpenAI's strict-mode
        # response_format. Log once per (model, endpoint) so operators know
        # they're on the prompt-only enforcement path, and proceed as today.
        # Client-side validation in JSONAgent.generate provides the safety net.
        if json_schema is not None:
            key = (self._text_model, self._ollama_url)
            if key not in _STRUCTURED_OUTPUTS_LOGGED:
                _STRUCTURED_OUTPUTS_LOGGED.add(key)
                # Inline event+counter to preserve the
                # ``autonomous.ai.models.local_model.event`` patch target
                # tests rely on (symmetric with openai_compat — DRYing
                # this into a helper was tried under #146 and reverted
                # because it broke the test seam).
                event(
                    "structured_outputs_unavailable",
                    level="warning",
                    marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
                    print_to_stdout=False,
                    provider="local",
                    model=self._text_model,
                    endpoint=self._ollama_url,
                    fallback="prompt_only_with_client_validation",
                )
                try:
                    _STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.inc(provider="local")
                except Exception as exc:  # noqa: BLE001
                    log(
                        f"[local_model] structured_outputs_unavailable_total "
                        f"counter inc failed: {exc!r}"
                    )

        # Message construction consolidated to ``_json_messages`` (#146) —
        # this adapter passes ``api_enforces_json=False`` because Ollama has
        # no ``response_format=json_object`` equivalent, so the prompt
        # carries the full enforcement burden (verbose JSON instructions +
        # "Adhere strictly to this context:" label + "No markdown, no
        # prose." suffix).
        # Caller-side `or` preserves the pre-#146 short-circuit: an explicit
        # `system_prompt` never triggers `self.instructions`'s descriptor
        # read. Tests pass system_prompt= against an instance whose `_data`
        # isn't initialized; resolving at the call site keeps them passing.
        # `system_msg` (not `system_prompt`) so the input parameter stays
        # accessible to any future retry/fallback path below.
        system_msg, user_message = build_chat_json_messages(
            message=message,
            system_base=system_prompt or self.instructions,
            context=context,
            uri=uri,
            api_enforces_json=False,
        )

        # 3. Payload Construction
        # NOTE: `format: json` (grammar-constrained sampling) is intentionally
        # omitted here. On CPU-only Ollama with a large model, constrained
        # sampling burns the token budget rejecting tokens and returns empty.
        # Instead, we rely on the system prompt instruction ("Output ONLY valid
        # JSON") and _clean_json_response() to extract valid JSON from free output.
        payload = {
            "model": self._text_model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            # Disable extended reasoning/thinking mode for Gemma4.
            # Without this, the model burns all num_predict tokens on internal
            # chain-of-thought and returns empty JSON output.
            "think": False,
            "options": {
                "num_ctx": self._context_limit,
                "num_predict": 1024,
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 64,
                "repeat_penalty": 1.1,
            },
        }

        log(
            "==== LocalAI JSON Payload ====", json.dumps(payload, indent=2), _print=True
        )

        # Per-attempt scratch — the closure mutates these so the on_retry
        # hook can decide whether to flush model memory.
        last_raw: dict = {"text": "", "response": None}

        def _attempt() -> dict:
            last_raw["text"] = ""
            last_raw["response"] = None
            if current_job := AutoTasks().get_current_task():
                current_job.meta(payload=payload)
            response = _HTTP.post(
                f"{self._ollama_url}/api/chat",
                json=payload,
                timeout=self._json_timeout,
            )
            last_raw["response"] = response
            response.raise_for_status()
            # Issue #142: route malformed-2xx through the shared helper so a
            # non-dict ``.json()`` body (list, scalar) becomes a typed
            # ``MalformedResponseError`` translated below to
            # ``GenerateJSONEmptyResponseError`` — symmetric with
            # ``openai_compat`` rather than leaking ``AttributeError``.
            result_text = extract_or_malformed(
                response,
                "/api/chat",
                lambda body: body.get("message", {}).get("content", "{}"),
            )
            last_raw["text"] = result_text
            if not result_text.strip():
                raise ValueError("Ollama returned empty content")
            result_dict = json.loads(self._clean_json_response(result_text))
            if "parameters" in result_dict and isinstance(
                result_dict["parameters"], dict
            ):
                result_dict.update(result_dict.pop("parameters"))
            return result_dict

        def _on_retry(attempt: int, exc: BaseException) -> None:
            log(
                f"==== LocalAI JSON Error (attempt {attempt}/3): {exc} ====",
                last_raw["response"],
                f"--- FAILED RAW OUTPUT ---\n{last_raw['text']}\n----------",
                _print=True,
            )
            # Flush KV cache on any failure. The empty-text case is
            # obviously "model stuck", but a model that keeps emitting
            # unparseable prose for the same prompt is equally stuck
            # (and retrying the same prompt without a flush burns
            # tokens for no benefit). Cheap to flush, expensive to skip.
            self.flush_memory(self._text_model)

        try:
            # ``catch`` lists ONLY concrete transient classes plus the
            # parse-failure exceptions ``_attempt`` translates. Using the
            # broad ``requests.RequestException`` would re-catch
            # ``requests.HTTPError`` (subclass) and burn the budget on a
            # permanent 4xx — the same fail-fast violation #91 fixed at
            # the HttpClient layer, recurring here at the outer-retry
            # altitude (closes #97 / #106). A documented trade: a bare
            # ``ChunkedEncodingError`` (a ``RequestException`` that is
            # NOT a ``ConnectionError`` / ``Timeout``) is no longer
            # retried — same trade flux's #85 narrowing made.
            return retry(
                _attempt,
                max_attempts=3,
                sleep_seconds=self._retry_sleep,
                catch=(
                    requests.ConnectionError,
                    requests.Timeout,
                    json.JSONDecodeError,
                    ValueError,
                    KeyError,
                ),
                on_retry=_on_retry,
            )
        except json.JSONDecodeError as exc:
            # Order matters: json.JSONDecodeError is a subclass of
            # ValueError, so this must come before the ValueError clause
            # below or it gets shadowed.
            #
            # _clean_json_response() couldn't extract valid JSON from the
            # model's free-form output. Model is producing prose; retry
            # with the same prompt usually won't help.
            raise GenerateJSONParseError(
                f"Could not parse JSON from Ollama response: {exc}",
                raw=last_raw["text"],
            ) from exc
        except ValueError as exc:
            # _attempt() raises ValueError("Ollama returned empty content")
            # for the empty-body case.
            raise GenerateJSONEmptyResponseError(
                f"Ollama returned no parseable content after retries: {exc}"
            ) from exc
        except KeyError as exc:
            # Server returned a shape we don't recognize (missing
            # "message" / "content"). Treat as empty for caller branching
            # since there's nothing to parse.
            raise GenerateJSONEmptyResponseError(
                f"Ollama response missing expected keys: {exc}"
            ) from exc
        except MalformedResponseError as exc:
            # Issue #142: a non-dict body (or any shape ``extract_or_malformed``
            # couldn't walk) escaped the retry as the typed exception.
            # Translate to the JSON-empty contract so callers see only the
            # documented ``GenerateJSONEmptyResponseError`` / ``ParseError``
            # surface — matches openai_compat.generate_json's behavior.
            raise GenerateJSONEmptyResponseError(
                f"Ollama returned a malformed 2xx body: {exc}"
            ) from exc

    def generate_text(
        self,
        message,
        additional_instructions="",
        uri="",
        context=None,
        temperature=0.7,
        evaluation=False,
    ):
        context = context or {}
        if context:
            additional_instructions += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"The following context is absolute truth for this interaction. "
                f"Prioritize it over your internal training data. "
                f"If the context says the sky is green, it is green.\n"
                f"{json.dumps(context, indent=2)}"
            )
        if uri:
            additional_instructions += f"\nUse the following URI for reference: {uri}"

        # 3. Send to Ollama
        payload = {
            "model": self._text_model,
            "messages": [
                {"role": "system", "content": additional_instructions},
                {"role": "user", "content": message},
            ],
            "stream": False,
            "keep_alive": "10m",
            "think": False,
            "options": {
                "num_ctx": self._context_limit,
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 64,
                "num_predict": -1,
                "repeat_penalty": 1.1,
            },
        }
        result = "Error generating text."
        try:
            if current_job := AutoTasks().get_current_task():
                current_job.meta(payload=payload)
            response = _HTTP.post(f"{self._ollama_url}/api/chat", json=payload, timeout=self._text_timeout)
            response.raise_for_status()
            if evaluation:
                eval_res = self._evaluate_response(
                    message, response, additional_instructions
                )
                log(f"Evaluation:\n {eval_res}")
                payload["messages"][1]["content"] = eval_res
                response = _HTTP.post(f"{self._ollama_url}/api/chat", json=payload, timeout=self._text_timeout)
                response.raise_for_status()
            # Issue #142: shared malformed-2xx translation.
            result = extract_or_malformed(
                response,
                "/api/chat",
                lambda body: body.get("message", {}).get("content", ""),
            )
        except (
            requests.RequestException,
            json.JSONDecodeError,
            ValueError,
            MalformedResponseError,
        ) as e:
            log(f"==== LocalAI Text Error: {e} ====", _print=True)
        return result

    def summarize_text(self, text, primer=""):
        primer = primer or "Summarize the following text concisely."
        max_chars = self._context_limit * 4
        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

        full_summary = ""
        for chunk in chunks:
            payload = {
                "model": self._text_model,
                "messages": [
                    {"role": "system", "content": primer},
                    {"role": "user", "content": chunk},
                ],
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": self._context_limit,
                    "num_predict": 1024,
                    "temperature": 0.5,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1,
                },
            }
            try:
                log(f"Payload sent: {payload}...", _print=True)
                if current_job := AutoTasks().get_current_task():
                    current_job.meta(payload=payload)
                res = _HTTP.post(f"{self._ollama_url}/api/chat", json=payload, timeout=self._summary_timeout)
                full_summary += res.json().get("message", {}).get("content", "") + "\n"
                log(f"Chunk summarized: {full_summary}.", _print=True)
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                log(f"Summary Error: {e}", _print=True)
                break
        return full_summary

    def generate_transcription(self, audio_file, prompt="", beam_size=5):
        if isinstance(audio_file, bytes):
            f_obj = io.BytesIO(audio_file)
        else:
            f_obj = audio_file

        files = {"file": ("audio.opus", f_obj, "audio/ogg")}
        data = {"prompt": prompt, "beam_size": beam_size}
        # orin-voice gates /transcribe behind a shared bearer token sourced from
        # ORIN_VOICE_TOKEN. Empty value → server rejects with 401; no special-
        # casing here so the misconfig surfaces loud rather than silent.
        headers = {"Authorization": f"Bearer {env_str('ORIN_VOICE_TOKEN', '')}"}
        try:
            if current_job := AutoTasks().get_current_task():
                current_job.meta(data=data)
            response = _HTTP.post(
                f"{self._audio_url}/transcribe",
                files=files,
                data=data,
                headers=headers,
                timeout=self._media_timeout,
            )
            response.raise_for_status()
            # Issue #142: validate the response is a dict via the extractor
            # so a non-dict body (list, scalar) translates to
            # ``MalformedResponseError`` and is caught below alongside the
            # other malformed-shape signals, preserving the existing
            # empty-result degrade contract.
            def _require_dict_body(body):
                if not isinstance(body, dict):
                    raise TypeError(
                        f"expected dict body, got {type(body).__name__}"
                    )
                return body

            return extract_or_malformed(
                response, "/transcribe", _require_dict_body
            )
        except (
            requests.RequestException,
            json.JSONDecodeError,
            ValueError,
            MalformedResponseError,
        ) as e:
            log(f"Transcription API Error: {e}", _print=True)
            return {"segments": [], "text": ""}

    def generate_audio(self, prompt, voice_description=None, voice_id=None):
        try:
            payload = {
                "text": prompt,
                "voice_id": voice_id or "",
                "voice_description": voice_description or "",
            }
            # Accept advertises ``audio/ogg`` (orin-voice returns opus-in-ogg —
            # passthrough avoids a wav→opus re-encode); ``audio/wav;q=0.5`` is
            # the legacy fallback so wav-only servers behind
            # ``MEDIA_AUDIO_API_BASE_URL`` still work. The branch below keys on
            # the actual response Content-Type, not the request preference.
            headers = {
                "Authorization": f"Bearer {env_str('ORIN_VOICE_TOKEN', '')}",
                "Accept": "audio/ogg, audio/wav;q=0.5",
            }
            if current_job := AutoTasks().get_current_task():
                current_job.meta(payload=payload)
            response = _HTTP.post(
                f"{self._audio_url}/tts",
                json=payload,
                headers=headers,
                timeout=self._media_timeout,
            )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            audio_bytes = response.content
            if "ogg" in content_type or "opus" in content_type:
                # Already opus-in-ogg, the storage format. Skip the
                # decode/re-encode round-trip.
                return audio_bytes
            # Anything else (audio/wav, audio/x-wav, unset Content-Type) goes
            # through the historical wav→opus transcode path.
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
            audio_buffer = io.BytesIO()
            audio.export(audio_buffer, format="opus")
            return audio_buffer.getvalue()
        except (requests.RequestException, OSError, ValueError, PydubException) as e:
            # ``PydubException`` covers ``CouldntDecodeError`` (raised when the
            # wav-path receives non-wav bytes — e.g. a misconfigured server
            # returns opus under empty Content-Type, hitting the defensive wav
            # default). It does NOT inherit from ``OSError`` so the original
            # catch tuple let it escape.
            log(f"TTS Error: {e}", _print=True)
            return None

    def _get_dimensions(self, aspect_ratio, style=""):
        """
        Returns a tuple: ((base_w, base_h), (target_w, target_h))
        Dynamically adjusts the base resolution depending on the target AI model
        to prevent anatomical hallucinations.
        """
        # 1. Determine which engine the server will auto-route to
        is_sdxl = any(a in style for a in ["atlas", "battlemap"])

        # 2. Base generation sizes (Engine specific)
        if is_sdxl:
            base_sizes = {
                "1:1": (1024, 1024),
                "3:4": (896, 1195),
                "4:3": (1195, 896),
                "16:9": (1104, 832),
                "9:16": (832, 1104),
            }
        else:
            # DreamShaper (SD 1.5) must stay near 512x512 to prevent extra limbs
            base_sizes = {
                "1:1": (512, 512),
                "3:4": (512, 680),
                "4:3": (680, 512),
                "16:9": (680, 512),
                "9:16": (512, 680),
            }

        # 3. Target final sizes (Upscale goals)
        target_sizes = {
            "1:1": (1024, 1024),
            "3:4": (1664, 2304),
            "4:3": (2304, 1664),
            "16:9": (2048, 1536),
            "9:16": (1536, 2048),
            "2K": (2048, 1536),
            "2KPortrait": (1536, 2048),
            "4K": (3840, 2880),
            "4KPortrait": (2880, 3840),
        }

        # Map complex aspect ratios to their core shapes for the base generation
        shape_mapper = {
            "2K": "16:9",
            "2KPortrait": "9:16",
            "4K": "16:9",
            "4KPortrait": "9:16",
        }

        core_shape = shape_mapper.get(aspect_ratio, aspect_ratio)

        base_w, base_h = base_sizes.get(core_shape, base_sizes["1:1"])
        target_w, target_h = target_sizes.get(aspect_ratio, target_sizes["1:1"])

        return (base_w, base_h), (target_w, target_h)

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="2KPortrait",
        style=None,
    ):
        # 1. Normalize the style parameter into a strict JSON string payload
        # and extract the core style name for internal routing.
        if isinstance(style, dict):
            style_str_payload = json.dumps(style)
            core_style_name = style.get("style", "")
        elif isinstance(style, str):
            style_str_payload = json.dumps({"style": style})
            core_style_name = style
        else:
            style_str_payload = "{}"
            core_style_name = ""

        # Pass core_style_name to ensure we get the right base dimensions for the engine
        (base_w, base_h), (target_w, target_h) = self._get_dimensions(
            aspect_ratio, core_style_name
        )

        data = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": base_w,
            "height": base_h,
            "style": style_str_payload,  # Guaranteed to be a valid JSON string
        }

        try:
            # Handle Input Files (for Img2Img and Compositing)
            file_obj = None
            if files and isinstance(files, dict):
                fn, f_bytes = random.choice(list(files.items()))
                if isinstance(f_bytes, bytes):
                    file_data = io.BytesIO(f_bytes)
                else:
                    file_data = f_bytes
                    file_data.seek(0)

                file_obj = (fn, file_data, "image/webp")

            # Step 1: Generate Base Image
            url = f"{self._image_url}/generate-image"
            if current_job := AutoTasks().get_current_task():
                current_job.meta(generation_data=json.dumps(data, indent=2))

            response = _HTTP.post(url, data=data, files={"file": file_obj}, timeout=self._media_timeout)

            response.raise_for_status()
            image_content = response.content

            log("==== LocalAI Image Generation Complete ====", data)
            return image_content

        except (requests.RequestException, OSError, ValueError) as e:
            log(f"Image Gen Error: {type(e)} - {e}", _print=True)
            return None

    def upscale_image(
        self, prompt, image_content, aspect_ratio="2KPortrait", style=None
    ):
        # Extract core style name for dimension checking to prevent dict vs string errors
        core_style_name = (
            style.get("style", "") if isinstance(style, dict) else (style or "")
        )

        (base_w, base_h), (target_w, target_h) = self._get_dimensions(
            aspect_ratio, core_style_name
        )

        if (base_w, base_h) != (target_w, target_h):
            log(f"Requesting AI Upscale: {base_w}x{base_h} -> {target_w}x{target_h}...")

            upscale_data = {
                "prompt": prompt,
                "width": target_w,
                "height": target_h,
            }

            upscale_files = {
                "file": ("generated.webp", io.BytesIO(image_content), "image/webp")
            }

            if current_job := AutoTasks().get_current_task():
                current_job.meta(
                    upscale_prompt=prompt,
                    upscale_target_size=(target_w, target_h),
                    upscale_original_size=(base_w, base_h),
                )
            upscale_response = _HTTP.post(
                f"{self._image_url}/upscale", data=upscale_data, files=upscale_files,
                timeout=self._media_timeout,
            )
            upscale_response.raise_for_status()
            return upscale_response.content

        # No-op upscale: base size already matches target. Return the
        # input image unchanged so callers (notably ImageAgent's hybrid
        # path) don't have to special-case a None return.
        return image_content
