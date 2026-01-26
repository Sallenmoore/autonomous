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
        """Helper to strip markdown artifacts from JSON responses."""
        text = text.strip()
        # Remove ```json ... ``` or just ``` ... ``` wrapper
        if text.startswith("```"):
            # Find the first newline to skip the language tag (e.g., "json")
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1 :]
            # Remove the closing backticks
            if text.endswith("```"):
                text = text[:-3]
        return text.strip()

    def generate_json(
        self, message, function, additional_instructions="", uri="", context={}
    ):
        schema_str = self._convert_tools_to_json_schema(function)

        # 1. Base System Prompt with Context Anchoring
        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You are a strict JSON generator. Output ONLY a valid JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"IMPORTANT: Do not include markdown formatting (like ```json), introductions, or explanations.\n"
        )

        if context:
            full_system_prompt += (
                f"\n\n### GROUND TRUTH CONTEXT ###\n"
                f"You must strictly adhere to the following context. "
                f"If this context contradicts your internal knowledge (e.g., physics, facts), "
                f"YOU MUST FOLLOW THE CONTEXT.\n"
                f"{json.dumps(context, indent=2)}"
            )
        elif uri:
            full_system_prompt += f"Use the following URI for reference: {uri}"

        # 3. Send to Ollama with JSON Mode
        payload = {
            "model": self._json_model,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": message},
            ],
            "format": "json",  # <--- CRITICAL: Forces valid JSON output
            "stream": False,
            "keep_alive": "24h",
        }

        try:
            # print(f"==== {self._ollama_url}: LocalAI JSON Payload ====")
            response = requests.post(f"{self._ollama_url}/chat", json=payload)
            response.raise_for_status()

            result_text = response.json().get("message", {}).get("content", "{}")

            # Clean up potential markdown artifacts
            clean_text = self._clean_json_response(result_text)

            # Parse
            result_dict = json.loads(clean_text)

            # Unwrap if the model nested it inside "parameters" (common Llama quirk)
            if "parameters" in result_dict and isinstance(
                result_dict["parameters"], dict
            ):
                params = result_dict.pop("parameters")
                result_dict.update(params)

            return result_dict

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            raise e

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
                res = requests.post(f"{self._ollama_url}/chat", json=payload)
                full_summary += res.json().get("message", {}).get("content", "") + "\n"
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
            "4K": (3840, 2160),
            "9:16": (832, 1216),
            "3:2": (1216, 832),
            "2:3": (832, 1216),
        }
        # Default to 1:1 (1024x1024) if unknown
        return resolutions.get(aspect_ratio, (1024, 1024))

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="3:4",
        image_size="2K",
    ):
        # 1. CLIP Token Limit Fix (Auto-Summarize)
        if len(prompt) > 300:
            log("⚠️ Prompt exceeds CLIP limit. rewriting...", _print=True)
            summary_instruction = (
                "Convert the description into a comma-separated Stable Diffusion prompt. "
                "Keep visual elements and style. Under 50 words."
            )
            new_prompt = self.generate_text(
                message=prompt, additional_instructions=summary_instruction, context={}
            )
            if new_prompt and len(new_prompt) > 10:
                prompt = new_prompt

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
            # Handle Files (Dict -> List of Tuples for requests)
            img_files = {}
            if files and isinstance(files, dict):
                for fn, f_bytes in files.items():
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes
                    img_files["file"] = (fn, file_obj, "image/png")

            # Send Request
            if img_files:
                response = requests.post(
                    f"{self._media_url}/generate-image", data=data, files=img_files
                )
            else:
                response = requests.post(f"{self._media_url}/generate-image", data=data)

            response.raise_for_status()
            return response.content

        except Exception as e:
            log(f"Image Gen Error: {e}", _print=True)
            return None
