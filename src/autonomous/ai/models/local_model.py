import io
import json
import os
import random
import time

import requests
from pydub import AudioSegment

from autonomous import log
from autonomous.ai.retry import retry
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.taskrunner.autotasks import AutoTasks


class LocalAIModel(AutoModel):
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(default="You are a helpful AI.")
    description = StringAttr(default="A Local AI Model using Ollama and Media AI.")

    # Config
    _ollama_url = os.environ.get("OLLAMA_API_BASE_URL", "")
    _media_url = os.environ.get("MEDIA_API_BASE_URL", "")
    _audio_url = os.environ.get("MEDIA_AUDIO_API_BASE_URL", "")
    _image_url = os.environ.get("MEDIA_IMAGE_API_BASE_URL", "")
    _text_model = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
    _context_limit = int(os.environ.get("OLLAMA_CONTEXT_LIMIT", 32768))

    # Timeouts (seconds) — CPU-only Ollama is slow; these prevent indefinite hangs
    _retry_sleep = int(os.environ.get("OLLAMA_RETRY_SLEEP", 30))       # sleep between JSON retries
    _json_timeout = int(os.environ.get("OLLAMA_JSON_TIMEOUT", 1200))   # 20 min
    _text_timeout = int(os.environ.get("OLLAMA_TEXT_TIMEOUT", 900))    # 15 min
    _summary_timeout = int(os.environ.get("OLLAMA_SUMMARY_TIMEOUT", 600))   # 10 min/chunk
    _media_timeout = int(os.environ.get("MEDIA_REQUEST_TIMEOUT", 300))  # 5 min

    def _convert_tools_to_json_schema(self, user_function):
        schema = {
            "name": user_function.get("name"),
            "description": user_function.get("description", ""),
            "parameters": user_function.get("parameters", {}),
        }
        return json.dumps(schema, indent=2)

    def _clean_json_response(self, text):
        """
        Robust cleaner for Llama 3 outputs.
        It handles markdown blocks, chatter before/after, and malformed endings.
        """
        text = text.strip()

        # 1. Strip Markdown Code Blocks (```json ... ```)
        if "```" in text:
            import re

            # Regex to capture content inside ```json ... ``` or just ``` ... ```
            # flags=re.DOTALL allows . to match newlines
            pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                # Fallback: simple finding if regex fails due to weird chars
                start = text.find("```")
                end = text.rfind("```")
                # Adjust start to skip the "json" part if present
                first_newline = text.find("\n", start)
                if first_newline != -1 and first_newline < end:
                    text = text[first_newline:end]

        # 2. Heuristic extraction: Find the first '{' and the last '}'
        # This fixes cases where the model says "Here is the JSON: { ... }"
        start_idx = text.find("{")
        end_idx = text.rfind("}")

        if start_idx != -1 and end_idx != -1:
            text = text[start_idx : end_idx + 1]
        elif text.strip():
            # Model returned JSON fields without the {} wrapper — add it.
            # e.g. '"name": "Aria", "desc": "..."' → '{"name": "Aria", "desc": "..."}'
            stripped = text.strip().rstrip(",")
            text = "{" + stripped + "}"

        return text.strip()

    def _evaluate_response(self, instruction, content, goal):
        eval_prompt = {
            "model": os.environ.get("OLLAMA_TEXT_MODEL", "gemma4:26b"),
            "messages": [
                {
                    "role": "user",
                    "content": f"Evaluate the original instruction and goal in regards to the output produced.\n\nGoal: {goal}\nInstruction: {instruction}\n\nOutput:\n{content}\n\n Write an improved prompt that will get the output closer to the stated goal. Only output the complete improved prompt. Do not preface it with any message.",
                }
            ],
            "stream": False,
        }
        res_eval = requests.post(f"{self._ollama_url}/chat", json=eval_prompt, timeout=self._text_timeout)

        return res_eval.json().get("message", {}).get("content", "")

    def flush_memory(self, model_name):
        """Forces Ollama to immediately unload the model from system RAM."""
        log(f"Flushing {model_name} from memory to free resources...", _print=True)
        try:
            # Sending keep_alive=0 triggers an immediate VRAM/RAM eviction
            requests.post(
                f"{self._ollama_url}/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30,
            )
        except requests.RequestException as e:
            log(f"Failed to flush memory: {e}", _print=True)

    def generate_json(
        self, message, system_prompt=None, uri="", context=None, evaluation=False
    ):
        context = context or {}
        system_prompt = system_prompt or self.instructions
        system_prompt = system_prompt.rstrip(". ") + "."
        system_prompt = (
            f"{system_prompt}\n"
            f"Your entire response MUST be a single valid JSON object.\n"
            f"Start with {{ and end with }}. No markdown, no prose."
        )

        # 2. Construct User Message
        user_message = message
        if context:
            user_message += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"Adhere strictly to this context:\n"
                f"{json.dumps(context, indent=2)}"
            )
        if uri:
            user_message += f"\nUse the following URI for reference: {uri}"
        user_message += "\n\nRespond with ONLY a valid JSON object. No markdown, no prose."

        # 3. Payload Construction
        # NOTE: `format: json` (grammar-constrained sampling) is intentionally
        # omitted here. On CPU-only Ollama with a large model, constrained
        # sampling burns the token budget rejecting tokens and returns empty.
        # Instead, we rely on the system prompt instruction ("Output ONLY valid
        # JSON") and _clean_json_response() to extract valid JSON from free output.
        payload = {
            "model": self._text_model,
            "messages": [
                {"role": "system", "content": system_prompt},
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
                "temperature": 0.7,
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
            response = requests.post(
                f"{self._ollama_url}/chat",
                json=payload,
                timeout=self._json_timeout,
            )
            last_raw["response"] = response
            response.raise_for_status()
            result_text = response.json().get("message", {}).get("content", "{}")
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
            if not last_raw["text"].strip():
                # Empty response — model is stuck. Flush KV cache so next
                # request gets a clean load rather than a corrupted state.
                self.flush_memory(self._text_model)

        return retry(
            _attempt,
            max_attempts=3,
            sleep_seconds=self._retry_sleep,
            catch=(
                requests.RequestException,
                json.JSONDecodeError,
                ValueError,
                KeyError,
            ),
            on_retry=_on_retry,
            default={},
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
            response = requests.post(f"{self._ollama_url}/chat", json=payload, timeout=self._text_timeout)
            response.raise_for_status()
            if evaluation:
                eval_res = self._evaluate_response(
                    message, response, additional_instructions
                )
                log(f"Evaluation:\n {eval_res}")
                payload["messages"][1]["content"] = eval_res
                response = requests.post(f"{self._ollama_url}/chat", json=payload, timeout=self._text_timeout)
                response.raise_for_status()
            result = response.json().get("message", {}).get("content", "")
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
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
                res = requests.post(f"{self._ollama_url}/chat", json=payload, timeout=self._summary_timeout)
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
        try:
            if current_job := AutoTasks().get_current_task():
                current_job.meta(data=data)
            response = requests.post(
                f"{self._audio_url}/transcribe",
                files=files,
                data=data,
                timeout=self._media_timeout,
            )
            response.raise_for_status()
            # Return the structured JSON dict containing 'segments'
            return response.json()
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            log(f"Transcription API Error: {e}", _print=True)
            return {"segments": [], "text": ""}

    def generate_audio(self, prompt, voice_description=None, voice_id=None):
        try:
            payload = {
                "text": prompt,
                "voice_id": voice_id or "",
                "voice_description": voice_description or "",
            }
            if current_job := AutoTasks().get_current_task():
                current_job.meta(payload=payload)
            response = requests.post(f"{self._audio_url}/tts", json=payload, timeout=self._media_timeout)
            response.raise_for_status()
            wav_bytes = response.content
            audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            audio_buffer = io.BytesIO()
            audio.export(audio_buffer, format="opus")
            return audio_buffer.getvalue()
        except (requests.RequestException, OSError, ValueError) as e:
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

            response = requests.post(url, data=data, files={"file": file_obj}, timeout=self._media_timeout)

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
            upscale_response = requests.post(
                f"{self._image_url}/upscale", data=upscale_data, files=upscale_files,
                timeout=self._media_timeout,
            )
            upscale_response.raise_for_status()
            return upscale_response.content
