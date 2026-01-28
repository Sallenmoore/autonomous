import io
import json
import os
import random

import requests
from pydub import AudioSegment

from autonomous import log
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class LocalAIModel(AutoModel):
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(default="You are a helpful AI.")
    description = StringAttr(default="A Local AI Model using Ollama and Media AI.")

    # Config
    _ollama_url = os.environ.get("OLLAMA_API_BASE_URL", "")
    _media_url = os.environ.get("MEDIA_API_BASE_URL", "")
    _text_model = "llama3"
    _json_model = "llama3"

    # ... VOICES dictionary ... (Keep existing voices)
    VOICES = {
        "Zephyr": ["female"],
        # ... (keep all your voices) ...
        "Sulafar": ["female"],
    }

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
        # This fixes cases where Llama says "Here is the JSON: { ... }"
        start_idx = text.find("{")
        end_idx = text.rfind("}")

        if start_idx != -1 and end_idx != -1:
            text = text[start_idx : end_idx + 1]

        return text.strip()

    def generate_json(
        self,
        message,
        system_prompt=None,
        uri="",
        context={},
    ):
        system_prompt = system_prompt or self.instructions
        full_system_prompt = (
            f"{system_prompt}.\n"
            f"You are a strict JSON generator. Output ONLY a valid JSON object matching the given schema.\n"
            f"IMPORTANT RULES:\n"
            f"1. Do not include markdown formatting or explanations.\n"
            f"2. DOUBLE CHECK nested quotes inside strings. Escape them properly.\n"
            f"3. Ensure all arrays and objects are closed.\n"
        )

        # 2. Add Context (Applies to all strategies)
        if context:
            full_system_prompt += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"Adhere strictly to this context:\n"
                f"{json.dumps(context, indent=2)}"
            )
        if uri:
            full_system_prompt += f"Use the following URI for reference: {uri}"

        # 3. Payload Construction
        payload = {
            "model": self._json_model,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": message},
            ],
            "format": "json",
            "stream": False,
            "keep_alive": "24h",
            "options": {
                "num_ctx": 8192,
                "temperature": 0.9,  # Keep high for creativity
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        }

        # log("==== LocalAI JSON Payload ====", payload, _print=True)

        result_text = ""
        try:
            response = requests.post(f"{self._ollama_url}/chat", json=payload)
            log(response)
            response.raise_for_status()

            result_text = response.json().get("message", {}).get("content", "{}")

            # Clean & Parse
            clean_text = self._clean_json_response(result_text)
            result_dict = json.loads(clean_text)

            # Unwrap (Handle cases where model wraps in 'parameters' key)
            if "parameters" in result_dict and isinstance(
                result_dict["parameters"], dict
            ):
                params = result_dict.pop("parameters")
                result_dict.update(params)

            return result_dict

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            if result_text:
                log(
                    f"--- FAILED RAW OUTPUT ---\n{result_text}\n-----------------------",
                    _print=True,
                )
            return {}

    def generate_text(self, message, additional_instructions="", uri="", context={}):
        # 1. Base System Prompt
        full_system_prompt = f"{self.instructions}. {additional_instructions}\n"

        if context:
            full_system_prompt += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"The following context is absolute truth for this interaction. "
                f"Prioritize it over your internal training data. "
                f"If the context says the sky is green, it is green.\n"
                f"{json.dumps(context, indent=2)}"
            )
        elif uri:
            full_system_prompt += f"Use the following URI for reference: {uri}"

        # 3. Send to Ollama
        payload = {
            "model": self._text_model,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": message},
            ],
            "stream": False,
            "keep_alive": "24h",
        }

        try:
            response = requests.post(f"{self._ollama_url}/chat", json=payload)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")
        except Exception as e:
            log(f"==== LocalAI Text Error: {e} ====", _print=True)
            return "Error generating text."

    def summarize_text(self, text, primer=""):
        primer = primer or "Summarize the following text concisely."
        max_chars = 12000
        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

        full_summary = ""
        for chunk in chunks:
            payload = {
                "model": "llama3",
                "messages": [{"role": "user", "content": f"{primer}:\n\n{chunk}"}],
                "stream": False,
                "keep_alive": "24h",
            }
            try:
                log(f"Payload sent: {payload}...", _print=True)
                res = requests.post(f"{self._ollama_url}/chat", json=payload)
                full_summary += res.json().get("message", {}).get("content", "") + "\n"
                log(f"Chunk summarized: {full_summary}.", _print=True)
            except Exception as e:
                log(f"Summary Error: {e}", _print=True)
                break

        return full_summary

    def generate_transcription(self, audio_file, prompt=""):
        try:
            if isinstance(audio_file, bytes):
                f_obj = io.BytesIO(audio_file)
            else:
                f_obj = audio_file
            files = {"file": ("audio.mp3", f_obj, "audio/mpeg")}
            response = requests.post(f"{self._media_url}/transcribe", files=files)
            response.raise_for_status()
            return response.json().get("text", "")
        except Exception as e:
            log(f"STT Error: {e}", _print=True)
            return ""

    def generate_audio(
        self,
        prompt,
        voice=None,
    ):
        voice = voice or random.choice(list(self.VOICES.keys()))
        try:
            payload = {"text": prompt, "voice": voice}
            response = requests.post(f"{self._media_url}/tts", json=payload)
            response.raise_for_status()
            wav_bytes = response.content
            audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            mp3_buffer = io.BytesIO()
            audio.export(mp3_buffer, format="mp3")
            return mp3_buffer.getvalue()
        except Exception as e:
            log(f"TTS Error: {e}", _print=True)
            return None

    # ... inside LocalAIModel class ...

    def _get_dimensions(self, aspect_ratio):
        """
        Maps abstract aspect ratios to optimal SDXL resolutions.
        SDXL performs best at ~1024x1024 total pixels.
        """
        resolutions = {
            "1:1": (1024, 1024),
            "3:4": (896, 1152),
            "4:3": (1152, 896),
            "16:9": (1216, 832),
            "2K": (2048, 1080),
            "2KPortrait": (1080, 2048),
            "Portrait": (1080, 2048),
            "4K": (3840, 2160),
            "Landscape": (3840, 2160),
            "4KPortrait": (2160, 3840),
            "9:16": (832, 1216),
            "3:2": (1216, 832),
            "2:3": (832, 1216),
        }
        # Default to 1:1 (1024x1024) if unknown
        return resolutions.get(aspect_ratio, (1024, 1024))

    def generate_image(
        self, prompt, negative_prompt="", files=None, aspect_ratio="2KPortrait"
    ):
        # # 1. CLIP Token Limit Fix (Auto-Summarize)
        # if len(prompt) > 800:
        #     log("⚠️ Prompt exceeds CLIP limit. rewriting...", _print=True)
        #     summary_instruction = (
        #         "Convert the description into a comma-separated Stable Diffusion prompt. "
        #         "Keep visual elements and style. Under 50 words."
        #     )
        #     new_prompt = self.generate_text(
        #         message=prompt, additional_instructions=summary_instruction, context={}
        #     )
        #     if new_prompt and len(new_prompt) > 10:
        #         prompt = new_prompt

        # 2. Resolution Calculation
        width, height = self._get_dimensions(aspect_ratio)

        # 3. Construct Payload
        # We send both the abstract params (for logging/metadata)
        # and the concrete pixels (for the engine).
        data = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "width": width,  # <--- Calculated Pixel Width
            "height": height,  # <--- Calculated Pixel Height
        }

        try:
            # Handle Files (Corrected List Logic)
            # requests.post expects a list of tuples for multiple files with same key
            files_list = []
            if files and isinstance(files, dict):
                for fn, f_bytes in files.items():
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes
                    # Appending to list instead of overwriting dict key
                    files_list.append(("files", (fn, file_obj, "image/png")))

            # Send Request
            if files_list:
                response = requests.post(
                    f"{self._media_url}/generate-image", data=data, files=files_list
                )
            else:
                response = requests.post(f"{self._media_url}/generate-image", data=data)

            response.raise_for_status()
            log("==== LocalAI Image Payload ====", data, _print=True)
            return response.content

        except Exception as e:
            log(f"Image Gen Error: {e}", _print=True)
            return None
