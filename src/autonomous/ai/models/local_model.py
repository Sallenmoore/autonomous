import io
import json
import os
import random

import requests
from PIL import Image
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
    _audio_url = os.environ.get("MEDIA_AUDIO_API_BASE_URL", "")
    _image_url = os.environ.get("MEDIA_IMAGE_API_BASE_URL", "")
    _text_model = "llama3"
    _json_model = "llama3"

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

        log("==== LocalAI JSON Payload ====", payload, _print=True)

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
            log("==== LocalAI JSON Result ====", result_dict, _print=True)
            return result_dict

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            if result_text:
                log(
                    f"--- FAILED RAW OUTPUT ---\n{result_text}\n-----------------------",
                    _print=True,
                )
            return {}

    def generate_text(
        self, message, additional_instructions="", uri="", context={}, temperature=0.9
    ):
        # 1. Base System Prompt

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
            "keep_alive": "24h",
            "options": {
                "num_ctx": 8192,
                # 1. ELIMINATE CREATIVITY
                "temperature": temperature,
                # 2. PREVENT CUTOFFS
                "num_predict": -1,
                # 3. PREVENT LOOPS
                "repeat_penalty": 1.1,
            },
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

            response = requests.post(f"{self._audio_url}/transcribe", files=files)
            response.raise_for_status()
            log(f"Transcription response: {response.json()}", _print=True)
            response_text = response.json().get("text", "")
            if ";;RAW_TRANSCRIPT_HERE" in prompt:
                prompt = prompt.replace(";;RAW_TRANSCRIPT_HERE", response_text)
            else:
                prompt += f"\nRAW TRANSCRIPT\n\n{response_text}"
            log(
                "==== TRANSCRIPTION PROMPT ====",
                prompt,
                f"TOKENS: {len(prompt.split())}",
                _print=True,
            )
            system_prompt = """
You are an expert Scribe and Editor. Your task is to transform a raw, automated audio transcript into a clean, readable script format.

GUIDELINES:
**Speaker Identification**: Use the Context to guess who is speaking to the best of your ability.
**Cleanup**: Remove verbal tics (um, uh, like, you know) and stuttering. Fix punctuation. Remove tangent conversations not relevant to the topic, such as "What did you do last weekend?", "Hand me some chips", etc.
**NO PREAMBLE**: Output ONLY the Markdown formatted script. Do not add introductory or concluding remarks.
"""
            result = self.generate_text(
                prompt, additional_instructions=system_prompt, temperature=0.1
            )
            log(f"FINAL TRANSCRIPTION CHUNK: {result}", _print=True)
            return result
        except Exception as e:
            log(f"STT Error: {e}", _print=True)
            return ""

    def list_voices(self, filters=[]):
        if not filters:
            return list(self.VOICES.keys())
        voices = []
        for voice, attribs in self.VOICES.items():
            if any(f.lower() in attribs for f in filters):
                voices.append(voice)
        return voices

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

    def _get_dimensions(self, aspect_ratio):
        """
        Returns a tuple: ((base_w, base_h), (target_w, target_h))

        1. base_*: The resolution sent to SDXL (approx 1024x1024).
        2. target_*: The final resolution to resize/upscale to.
        """
        # Standard SDXL buckets (approx 1MP)
        # We use these for the initial generation to ensure good composition.
        sdxl_base = {
            "1:1": (1024, 1024),
            "Portrait": (896, 1152),  # 3:4
            "Landscape": (1216, 832),  # 3:2 or 16:9 approx
        }

        # The Logic: Define the target, map it to the closest SDXL base
        # Format: "Key": ((Base_W, Base_H), (Target_W, Target_H))
        resolutions = {
            # Standard
            "1:1": ((832, 832), (1024, 1024)),
            "3:4": ((832, 1152), (1664, 2304)),
            "4:3": ((1152, 832), (2304, 1664)),
            # High Res (The logic changes here)
            "16:9": ((1216, 832), (2048, 1152)),
            "9:16": ((832, 1216), (1152, 2048)),
            # 2K Tier
            "2K": ((1216, 832), (2048, 1152)),  # Base is 1216x832 -> Upscale to 2K
            "2KPortrait": ((832, 1216), (1152, 2048)),
            # 4K Tier (The generated image will be upscaled ~3x)
            "4K": ((1216, 832), (3840, 2160)),
            "4KPortrait": ((832, 1216), (2160, 3840)),
        }

        # Default to 1:1 if unknown
        return resolutions.get(aspect_ratio, ((832, 832), (1024, 1024)))

    def generate_image(
        self, prompt, negative_prompt="", files=None, aspect_ratio="2KPortrait"
    ):
        # 1. Resolution Calculation
        (base_w, base_h), (target_w, target_h) = self._get_dimensions(aspect_ratio)

        # 2. Construct Base Generation Payload
        # We tell the AI to generate the smaller, stable size first.
        data = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "width": base_w,
            "height": base_h,
        }

        try:
            # Handle Input Files (for Img2Img)
            files_list = []
            if files and isinstance(files, dict):
                for fn, f_bytes in files.items():
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes
                    files_list.append(("files", (fn, file_obj, "image/png")))

            # 3. Step 1: Generate Base Image
            url = f"{self._image_url}/generate-image"
            if files_list:
                response = requests.post(url, data=data, files=files_list)
            else:
                response = requests.post(url, data=data)

            response.raise_for_status()
            image_content = response.content

            # 4. Step 2: Upscale (If necessary)
            if (base_w, base_h) != (target_w, target_h):
                log(
                    f"Requesting AI Upscale: {base_w}x{base_h} -> {target_w}x{target_h}...",
                    _print=True,
                )

                # Prepare payload for the /upscale route
                upscale_data = {
                    "prompt": prompt,  # Reuse prompt to guide texture generation
                    "width": target_w,  # Explicitly tell server the target size
                    "height": target_h,
                }

                # Send the image we just generated back to the server as a file
                upscale_files = {
                    "file": ("generated.png", io.BytesIO(image_content), "image/png")
                }

                upscale_response = requests.post(
                    f"{self._image_url}/upscale", data=upscale_data, files=upscale_files
                )
                upscale_response.raise_for_status()
                image_content = upscale_response.content

            log("==== LocalAI Image Generation Complete ====", data, _print=True)
            return image_content

        except Exception as e:
            log(f"Image Gen Error: {e}", _print=True)
            return None
