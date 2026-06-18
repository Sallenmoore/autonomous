import io
import json
import os
import re
import time
import wave
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types
from google.genai.types import Part
from pydub import AudioSegment

from autonomous import log
from autonomous.ai.exceptions import (
    GeminiFileUploadTimeoutError,
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
)
from autonomous.ai.models._image_utils import resolve_image_config
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class GeminiAIModel(AutoModel):
    _client = None

    # Model definitions — every default is env-overridable so deployments
    # can chase Gemini's preview-model churn without a library release.
    # The defaults track what Google has stable / preview as of the most
    # recent release of this library; any deployment seeing a 404
    # (e.g. "gemini-2.0-flash-exp is not found") should set the env var
    # to a currently-available model name from
    # https://ai.google.dev/gemini-api/docs/models without waiting on
    # an autonomous bump.
    _text_model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-pro")
    _summary_model = os.environ.get("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash")
    _json_model = os.environ.get("GEMINI_JSON_MODEL", "gemini-2.5-pro")
    _stt_model = os.environ.get("GEMINI_STT_MODEL", "gemini-2.5-pro")
    _image_model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    _tts_model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")

    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with various tasks."
    )
    file_refs = ListAttr(StringAttr(default=[]))

    MAX_FILES = 14
    MAX_SUMMARY_TOKEN_LENGTH = 10000

    SAFETY_SETTINGS = [
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_CIVIC_INTEGRITY",
            threshold="BLOCK_NONE",
        ),
    ]

    VOICES = {
        "Zephyr": ["female"],
        "Puck": ["male"],
        "Charon": ["male"],
        "Kore": ["female"],
        "Fenrir": ["non-binary"],
        "Leda": ["female"],
        "Orus": ["male"],
        "Aoede": ["female"],
        "Callirhoe": ["female"],
        "Autonoe": ["female"],
        "Enceladus": ["male"],
        "Iapetus": ["male"],
        "Umbriel": ["male"],
        "Algieba": ["male"],
        "Despina": ["female"],
        "Erinome": ["female"],
        "Algenib": ["male"],
        "Rasalgethi": ["non-binary"],
        "Laomedeia": ["female"],
        "Achernar": ["female"],
        "Alnilam": ["male"],
        "Schedar": ["male"],
        "Gacrux": ["female"],
        "Pulcherrima": ["non-binary"],
        "Achird": ["male"],
        "Zubenelgenubi": ["male"],
        "Vindemiatrix": ["female"],
        "Sadachbia": ["male"],
        "Sadaltager": ["male"],
        "Sulafar": ["female"],
    }

    @property
    def client(self):
        if not self._client:
            self._client = genai.Client(api_key=os.environ.get("GOOGLEAI_KEY"))
        return self._client

    def _add_function(self, user_function):
        # Guard against None — the canonical failure mode when JSONAgent
        # dispatches to gemini without a json_schema= (or a caller invokes
        # GeminiAIModel.generate_json directly with function= omitted /
        # passed as None). Pre-guard, this raised AttributeError on
        # `.get("name")` from deep inside this method (issue #21);
        # surface ValueError with a pointer to the API instead.
        if user_function is None:
            raise ValueError(
                "GeminiAIModel.generate_json requires function= (or "
                "json_schema= via JSONAgent.generate). Got None."
            )
        tool_schema = {
            "name": user_function.get("name"),
            "description": user_function.get("description"),
            "parameters": user_function.get("parameters"),
        }
        if not all(
            [tool_schema["name"], tool_schema["description"], tool_schema["parameters"]]
        ):
            raise ValueError(
                "Tool schema must have a 'name', 'description', and 'parameters' field."
            )
        return tool_schema

    def _create_wav_header(
        self, raw_audio_bytes, channels=1, rate=24000, sample_width=2
    ):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(rate)
            wav_file.writeframes(raw_audio_bytes)
        buffer.seek(0)
        return buffer

    def _add_context(self, context):
        context_data = (
            json.dumps(context, indent=2) if isinstance(context, dict) else str(context)
        )
        f = io.BytesIO(context_data.encode("utf-8"))
        f.name = f"context-{self.pk}"
        return self._add_files([{"name": f.name, "file": f}])

    def _add_files(self, file_list, mime_type="application/json"):
        # Accepts either a list of {"name", "file"} dicts (from
        # _add_context) or a {filename: fileobj} dict (from
        # generate_image / ImageAgent); normalize both to one shape.
        if isinstance(file_list, dict):
            # Subset check (not exact-equality): any dict containing both
            # "name" and "file" keys is a single-file misuse, regardless
            # of extra metadata keys.
            #
            # NOTE: the phrase "with both 'name' and 'file' keys" below
            # is load-bearing as a test discriminator vs. the value-shape
            # error in the inner loop. Reword only with a matching test
            # update.
            if "name" in file_list and "file" in file_list:
                raise TypeError(
                    "_add_files received a dict with both 'name' and 'file' "
                    "keys, suggesting a single-file misuse. Wrap it in a list "
                    "([{'name': ..., 'file': ...}]) or pass "
                    "{filename: fileobj, ...} with multiple distinct "
                    "filenames."
                )
            normalized = []
            for fn, fobj in file_list.items():
                # Per-value guard: catches asymmetric typos that smuggle
                # a non-file value into the fileobj slot.
                # NOTE: "file-like object or bytes" is also a load-bearing
                # discriminator phrase — see test comment above.
                if not (hasattr(fobj, "read") or isinstance(fobj, (bytes, bytearray))):
                    raise TypeError(
                        f"_add_files: value for key {fn!r} is not a "
                        f"file-like object or bytes; got "
                        f"{type(fobj).__name__}: {fobj!r}. Did you "
                        f"mean to pass a single-item list "
                        f"[{{'name': ..., 'file': ...}}] instead of "
                        f"the {{filename: fileobj}} dict form?"
                    )
                normalized.append({"name": fn, "file": fobj})
        elif isinstance(file_list, (list, tuple)):
            normalized = list(file_list)
            for entry in normalized:
                if not (
                    isinstance(entry, dict)
                    and "name" in entry
                    and "file" in entry
                ):
                    raise TypeError(
                        f"_add_files list entries must be "
                        f"{{'name', 'file'}} dicts; got "
                        f"{type(entry).__name__}: {entry!r}."
                    )
        else:
            raise TypeError(
                f"_add_files expects a list-of-dicts or "
                f"{{filename: fileobj}} dict; got "
                f"{type(file_list).__name__}: {file_list!r}."
            )

        uploaded_files = []
        for f in normalized[: self.MAX_FILES]:
            fn = f["name"]
            try:
                self.client.files.delete(name=fn)
            except genai.errors.APIError:
                # file may not exist, is still propagating, or is already gone
                pass

            file_content = f["file"]
            fileobj = (
                io.BytesIO(file_content)
                if isinstance(file_content, bytes)
                else file_content
            )

            uploaded_file = self.client.files.upload(
                file=fileobj,
                config={"mime_type": mime_type, "display_name": fn},
            )
            uploaded_files.append(uploaded_file)

            # Bounded poll for the upload to leave PROCESSING. Pre-#50 this
            # loop was unbounded — a file genuinely stuck would spin the
            # worker forever. Wall-clock cap (time.monotonic, immune to
            # NTP / wall-clock skew) over a max-attempt count keeps the
            # bound stable if poll_interval ever changes. README #6.
            poll_timeout = float(os.environ.get("GEMINI_UPLOAD_POLL_TIMEOUT", "300"))
            deadline = time.monotonic() + poll_timeout
            try:
                while uploaded_file.state.name == "PROCESSING":
                    if time.monotonic() >= deadline:
                        raise GeminiFileUploadTimeoutError(
                            f"Gemini file {uploaded_file.name!r} stuck in PROCESSING "
                            f"after {poll_timeout:.1f}s — giving up"
                        )
                    time.sleep(0.5)
                    # google-genai >=2.0 exposes the poll via
                    # ``client.files.get(name=...)`` — ``client.get_file``
                    # does not exist on the modern Client. The earlier
                    # bare ``self.client.get_file(...)`` would have
                    # AttributeError'd at runtime against the real SDK
                    # (MagicMock silently accepts any attribute access,
                    # which is why the broken call passed type-blind
                    # mocks). Fixed alongside #75 because the new
                    # orphan-cleanup is dead code if the poll itself
                    # can't even run.
                    uploaded_file = self.client.files.get(name=uploaded_file.name)
            except Exception:
                # Orphan cleanup (#75, broadened in #84): every file
                # appended to ``uploaded_files`` is now stranded on
                # Gemini's side — either still PROCESSING (the one we
                # just gave up on) or already ACTIVE from a prior
                # outer-loop iteration the caller will never see. The
                # outer except is broad (was ``(GeminiFileUploadTimeoutError,
                # genai.errors.APIError)``) so cleanup runs on every
                # poll-loop failure mode the SDK can throw — notably
                # ``genai.errors.UnknownApiResponseError``, which
                # subclasses ``ValueError`` rather than ``APIError`` and
                # would have skipped cleanup under the narrower tuple.
                # The ``raise`` re-raises the original, so widening the
                # catch doesn't change which exception reaches the
                # caller; it only widens which exceptions still trigger
                # cleanup before propagating.
                def _delete_orphan(orphan):
                    # ``google.genai.types.File.name`` is typed
                    # ``Optional[str]`` — a partial upload may yield a
                    # handle with ``name=None`` (or, in degenerate SDK
                    # cases, missing the attr entirely). Skip up front
                    # so cleanup doesn't waste an API call and operator
                    # logs don't fill with ``files.delete(name=None)``
                    # TypeErrors. ``getattr`` (not ``orphan.name``)
                    # defends against an SDK that drops the attr entirely.
                    name = getattr(orphan, "name", None)
                    if name is None:
                        return
                    try:
                        self.client.files.delete(name=name)
                    except Exception as cleanup_exc:
                        # Already on the cleanup path — never let anything
                        # (APIError, TypeError, network blip) mask the
                        # original poll exception that ``raise`` below
                        # re-throws. But LOG it (#93): the prior silent
                        # ``pass`` made every cleanup failure invisible, so
                        # a future SDK schema change rejecting some
                        # ``orphan.name`` format would leak Gemini file
                        # quota for weeks with no operator signal until
                        # quota exhaustion blocked new uploads. _print=False
                        # keeps it in the log file only — the original poll
                        # exception is what the user sees.
                        log(
                            f"==== Gemini orphan-cleanup delete failed for "
                            f"{name!r}: {type(cleanup_exc).__name__}: "
                            f"{cleanup_exc} ====",
                            _print=False,
                        )

                # Parallel deletes (#94): N serial blocking ``files.delete``
                # calls — each able to approach the per-call timeout under
                # the same degraded Gemini conditions that triggered this
                # failure path — can sum past the outer RQ job deadline,
                # replacing the typed ``GeminiFileUploadTimeoutError`` the
                # ``raise`` below re-throws with an
                # ``rq.exceptions.JobTimeoutError``. A bounded thread pool
                # caps wall-clock to roughly the slowest single delete;
                # each ``files.delete`` is an independent HTTP call, so
                # concurrency is safe. ``list(...)`` forces every delete to
                # finish (and log) before ``raise`` propagates;
                # ``_delete_orphan`` swallows its own errors so ``map``
                # never raises.
                with ThreadPoolExecutor(max_workers=4) as executor:
                    list(executor.map(_delete_orphan, uploaded_files))
                raise

        self.file_refs = [f.name for f in self.client.files.list()]
        self.save()
        return uploaded_files

    def generate_json(
        self,
        message,
        system_prompt=None,
        json_schema=None,
        schema_name="response",
        uri="",
        context=None,
        temperature=None,
    ):
        # Canonical AIModelProtocol signature (#47 slice 3). Translation
        # to gemini's native ``function=`` dict happens inline here —
        # callers (including JSONAgent) pass ``json_schema`` /
        # ``schema_name`` / ``system_prompt`` exactly like every other
        # provider, and gemini handles the gemini-specific tool-call
        # mechanics internally. Pre-slice-3 this translation lived in
        # ``jsonagent.py`` behind ``if provider == "gemini":`` — the
        # forcing function for every new agent method or adapter quirk
        # to ripple into the dispatch layer. That branch is now gone.
        if json_schema is None:
            raise ValueError(
                "GeminiAIModel.generate_json requires json_schema=. "
                "Gemini's structured-output path is tool-calling, which "
                "needs a parameter schema. Pass via JSONAgent.generate("
                "json_schema=...) or set the kwarg directly."
            )
        function = {
            "name": schema_name,
            "description": "Structured response shape.",
            "parameters": json_schema,
        }
        additional_instructions = system_prompt or ""
        context = context or {}
        function_definition = self._add_function(function)
        contents = [message]

        if context:
            contents.extend(self._add_context(context))
            additional_instructions += (
                f"\nUse the uploaded context file for reference: context-{self.pk}\n"
            )

        if uri:
            contents.append(Part.from_uri(file_uri=uri, mime_type="application/json"))
            additional_instructions += "\nUse the provided uri file for reference\n"

        config_kwargs = {
            "system_instruction": f"{self.instructions}.{additional_instructions}",
            "tools": [types.Tool(function_declarations=[function_definition])],
            "tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        }
        if temperature is not None:
            config_kwargs["temperature"] = temperature

        response = self.client.models.generate_content(
            model=self._json_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        # Empty-content guard: Gemini's safety filters can drop the
        # candidate's ``.content`` entirely (returns ``content=None`` rather
        # than an empty parts list). Reach in only after each level proves
        # non-None — accessing ``.parts`` on ``None.content`` would otherwise
        # raise AttributeError, which the outer except would misclassify as
        # ParseError. MIGRATIONS contract says "no candidates / no content
        # parts" is the EmptyResponse mode.
        no_content = (
            not response.candidates
            or response.candidates[0].content is None
            or not response.candidates[0].content.parts
        )
        if no_content:
            raise GenerateJSONEmptyResponseError(
                "Gemini returned no candidates / no content parts."
            )

        try:
            tool_call = response.candidates[0].content.parts[0].function_call
            if tool_call and tool_call.name == function["name"]:
                return tool_call.args
            # No matching function_call — the model returned prose or
            # called a different tool. Surface the raw response so the
            # caller can decide whether to retry or change the prompt.
            raw = ""
            try:
                raw = response.text or ""
            except (AttributeError, TypeError) as text_exc:
                # response.text can raise if the candidate has no text
                # accessor (tool-only response, or SDK schema drift).
                # Log it so the failure mode is visible — leaving raw=""
                # would otherwise look identical to a wrong-tool response.
                log(
                    f"==== Could not read Gemini response.text: {text_exc} ====",
                    _print=True,
                )
            log(f"Response: {raw[:500]}", _print=True)
            raise GenerateJSONParseError(
                f"Gemini did not call function {function['name']!r}; "
                f"returned prose or wrong tool.",
                raw=raw,
            )
        except (AttributeError, IndexError, KeyError, TypeError) as e:
            log(f"==== Failed to parse ToolCall response: {e} ====")
            raise GenerateJSONParseError(
                f"Could not parse Gemini ToolCall response: {e}",
                raw="",
            ) from e

    def generate_text(
        self,
        message,
        additional_instructions="",
        uri="",
        context=None,
        temperature=None,
        system_prompt=None,
    ):
        context = context or {}
        contents = [message]
        if context:
            contents.extend(self._add_context(context))
            additional_instructions += (
                f"\nUse the uploaded context file for reference: context-{self.pk}\n"
            )

        if uri:
            contents.append(Part.from_uri(file_uri=uri, mime_type="application/json"))

        # system_prompt replaces the persisted persona for this call
        # (mirrors generate_json). additional_instructions still appends.
        base_system = system_prompt or self.instructions
        config_kwargs = {
            "system_instruction": f"{base_system}.{additional_instructions}",
        }
        if temperature is not None:
            config_kwargs["temperature"] = temperature

        response = self.client.models.generate_content(
            model=self._text_model,
            config=types.GenerateContentConfig(**config_kwargs),
            contents=contents,
        )
        return response.text

    def summarize_text(self, text, primer=""):
        primer = primer or self.instructions
        updated_prompt_list = []
        words = re.findall(r"\w+", text)

        for i in range(0, len(words), self.MAX_SUMMARY_TOKEN_LENGTH):
            updated_prompt_list.append(
                " ".join(words[i : i + self.MAX_SUMMARY_TOKEN_LENGTH])
            )

        full_summary = ""
        for p in updated_prompt_list:
            response = self.client.models.generate_content(
                model=self._summary_model,
                config=types.GenerateContentConfig(system_instruction=f"{primer}"),
                contents=p,
            )
            try:
                summary = response.candidates[0].content.parts[0].text
                full_summary += summary + "\n"
            except (AttributeError, IndexError, genai.errors.APIError) as e:
                log(f"Summary Error: {e}", _print=True)
                break
        return full_summary

    def generate_transcription(
        self, audio_file, prompt="Transcribe this audio clip", display_name="audio.mp3"
    ):
        myfile = self.client.files.upload(
            file=io.BytesIO(audio_file),
            config={"mime_type": "audio/mp3", "display_name": display_name},
        )
        response = self.client.models.generate_content(
            model=self._stt_model,
            contents=[prompt, myfile],
        )
        # #47 slice 4 — AIModelProtocol pins the return shape as
        # ``{"text": str, "segments": list}`` to match the verbose-json
        # contract that audioagent.transcribe / dramatize and consumer
        # screenplay post-processing expect. Gemini's tool-only
        # response carries the text directly; it doesn't expose per-
        # phrase segments the way Whisper does, so segments is an
        # empty list (NOT missing/None — consumers can still
        # ``for seg in result["segments"]`` without a TypeError).
        return {"text": response.text or "", "segments": []}

    def list_voices(self, filters=None):
        if not filters:
            return list(self.VOICES.keys())
        voices = []
        for voice, attribs in self.VOICES.items():
            if any(f.lower() in attribs for f in filters):
                voices.append(voice)
        return voices

    def generate_audio(self, prompt, voice_description=None, voice_id=None):
        presets = self.list_voices()
        voice = presets[hash(voice_id) % len(presets)] if voice_id else "Algieba"
        try:
            response = self.client.models.generate_content(
                model=self._tts_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice
                            )
                        )
                    ),
                ),
            )
            blob = response.candidates[0].content.parts[0].inline_data
            wav_buffer = self._create_wav_header(blob.data)
            audio_segment = AudioSegment.from_file(wav_buffer, format="wav")
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3")
            return mp3_buffer.getvalue()
        except (genai.errors.APIError, OSError, ValueError) as e:
            log(f"==== Audio Gen Error: {e} ====", _print=True)
            raise

    # Per-tier wire-shape mapping for Gemini. Pre-#149 these branches
    # were inline in _get_image_config; pulling the vocabulary parse out
    # (see _image_utils.resolve_image_config) lets us collapse the
    # duplicated mapping with Flux.
    #
    # Image-size constraints (issues #29, #30):
    # - Gemini's ``types.ImageConfig.image_size`` accepts ``"1K"`` /
    #   ``"2K"`` / ``"4K"``. ``"0.5K"`` is NOT a valid value — the API
    #   returns ``400 INVALID_ARGUMENT``.
    # - The current default model ``gemini-3.1-flash-image-preview``
    #   additionally rejects ``"4K"`` (only ``"1K"`` / ``"2K"`` work
    #   against it). The "4K" tier is therefore clamped to "2K" in the
    #   wire-shape table below; ``_get_image_config`` logs a breadcrumb
    #   so callers can detect the silent downgrade.
    _GEMINI_SIZE_BY_TIER = {
        "low": "1K",  # was "0.5K" — issue #29 (invalid for Gemini)
        "2K":  "2K",
        "4K":  "2K",  # was "4K" — issue #30 (flash-image-preview rejects 4K)
    }

    def _get_image_config(self, aspect_ratio_input):
        """Map autonomous's aspect-ratio vocabulary to Gemini's
        ``(aspect_ratio, image_size)`` pair.

        Canonical vocabulary parse lives in
        ``_image_utils.resolve_image_config``; this method only
        translates the canonical ``(ratio, tier)`` to Gemini's wire
        shape plus the "4K"→"2K" clamp breadcrumb.
        """
        ratio, tier = resolve_image_config(aspect_ratio_input)
        if tier == "4K":
            # Breadcrumb so a 4K caller can detect the silent downgrade.
            # The clamp policy is correct (return *something* rather than
            # hard-fail), but the silence was: storyteller workers stored
            # the WebP and had no way to know the resolution contract was
            # downgraded. Mirrors imageagent.py's breadcrumb pattern
            # (hybrid_upscale / provider_fallback_used).
            log(
                f"[GEMINI-IMAGE-CLAMP] aspect_ratio={aspect_ratio_input!r} "
                f"requested 4K resolution; clamped to image_size='2K' "
                f"(model {self._image_model!r} rejects 4K). Set "
                f"GEMINI_IMAGE_MODEL to a 4K-capable variant to lift.",
                _print=False,
            )
        size = self._GEMINI_SIZE_BY_TIER.get(tier, "1K")
        return ratio, size

    def generate_image(
        self, prompt, negative_prompt="", files=None, aspect_ratio="2K", style=""
    ):
        # negative_prompt accepted to honor the cross-provider interface
        # but ignored: gemini-3.x-flash-image-preview's ImageConfig has no
        # negative-prompt slot. Phrase the prompt positively instead.
        image = None
        style_str_payload = ""
        if isinstance(style, dict):
            style_str_payload = json.dumps(style)
        elif isinstance(style, str):
            style_str_payload = json.dumps({"style": style})

        contents = [f"{prompt}. {style_str_payload}"]

        if files:
            filerefs = self._add_files(files, mime_type="image/webp")
            contents.extend(filerefs)

        try:
            # 1. Resolve Aspect Ratio AND Size
            valid_ratio, valid_size = self._get_image_config(aspect_ratio)

            # 2. Call API with correct parameters
            response = self.client.models.generate_content(
                model=self._image_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    safety_settings=self.SAFETY_SETTINGS,
                    image_config=types.ImageConfig(
                        aspect_ratio=valid_ratio,
                        image_size=valid_size,
                    ),
                ),
            )

            # 3. Extract Image Data
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        image = part.inline_data.data
                        break

            if not image:
                raise ValueError(
                    f"API returned Success but no image data found. Response: {response}"
                )

        except (genai.errors.APIError, ValueError, OSError) as e:
            log(f"==== Error: Unable to create image ====\n\n{e}", _print=True)
            raise

        return image

    def upscale_image(
        self, prompt, image_content=None, aspect_ratio="2KPortrait", style=None
    ):
        # Gemini's image API has no dedicated upscaler; the prior
        # implementation re-issued a full generate_content call with the
        # input image attached, which billed as a fresh image generation
        # without any guarantee of resolution improvement. Returning the
        # input unchanged is the honest contract: callers that want
        # actual upscaling should route through ImageAgent's hybrid
        # path (IMAGE_HYBRID_UPSCALE=1) or use the local provider.
        log(
            "Gemini does not support image upscaling; "
            "returning input image unchanged.",
            _print=False,
        )
        return image_content
