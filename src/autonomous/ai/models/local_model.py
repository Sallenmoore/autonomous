import io
import json
import os
import random
import re
import wave

import requests
from pydub import AudioSegment

from autonomous import log
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class LocalAIModel(AutoModel):
    # Configuration
    _ollama_url = os.environ.get("OLLAMA_API_BASE", "http://ollama_internal:11434/api")
    _media_url = os.environ.get("MEDIA_API_BASE", "http://media_ai_internal:5005")

    # Models to use in Ollama
    _text_model = "mistral-nemo"
    _json_model = "mistral-nemo"

    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )

    # Keep your voice list (mapped to random seeds/embeddings in the future)
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
        """
        Ollama doesn't support 'tools' strictly yet.
        We convert the tool definition into a system prompt instruction.
        """
        schema = {
            "name": user_function.get("name"),
            "parameters": user_function.get("parameters"),
        }
        return json.dumps(schema, indent=2)

    def generate_json(self, message, function, additional_instructions="", **kwargs):
        """
        Mimics Gemini's tool use by forcing Ollama into JSON mode
        and injecting the schema into the prompt.
        """
        schema_str = self._convert_tools_to_json_schema(function)

        system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must respond strictly with a valid JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"Do not include markdown formatting or explanations."
        )

        payload = {
            "model": self._json_model,
            "prompt": message,
            "system": system_prompt,
            "format": "json",  # Force JSON mode
            "stream": False,
        }

        try:
            response = requests.post(f"{self._ollama_url}/generate", json=payload)
            response.raise_for_status()
            result_text = response.json().get("response", "{}")

            # log(f"Raw Local JSON: {result_text}", _print=True)
            return json.loads(result_text)

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            return {}

    def generate_text(self, message, additional_instructions="", **kwargs):
        """
        Standard text generation via Ollama.
        """
        payload = {
            "model": self._text_model,
            "prompt": message,
            "system": f"{self.instructions}. {additional_instructions}",
            "stream": False,
        }

        # Handle 'files' (Ollama supports images in base64, but not arbitrary files easily yet)
        # If files are text, you should read them and append to prompt.
        if file_list := kwargs.get("files"):
            for file_dict in file_list:
                fn = file_dict["name"]
                fileobj = file_dict["file"]
                if fn.lower().endswith((".txt", ".md", ".json", ".csv")):
                    content = fileobj.read()
                    if isinstance(content, bytes):
                        content = content.decode("utf-8", errors="ignore")
                    payload["prompt"] += f"\n\nContents of {fn}:\n{content}"

        try:
            response = requests.post(f"{self._ollama_url}/generate", json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            log(f"==== LocalAI Text Error: {e} ====", _print=True)
            return "Error generating text."

    def summarize_text(self, text, primer="", **kwargs):
        primer = primer or "Summarize the following text concisely."

        # Simple chunking logic (similar to your original)
        # Note: Mistral-Nemo has a large context window (128k), so chunking
        # is less necessary than with older models, but we keep it for safety.
        max_chars = 12000  # Roughly 3k tokens
        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

        full_summary = ""
        for chunk in chunks:
            payload = {
                "model": self._text_model,
                "prompt": f"{primer}:\n\n{chunk}",
                "stream": False,
            }
            try:
                res = requests.post(f"{self._ollama_url}/generate", json=payload)
                full_summary += res.json().get("response", "") + "\n"
            except Exception as e:
                log(f"Summary Error: {e}", _print=True)
                break

        return full_summary

    def generate_audio_text(self, audio_file, prompt="", **kwargs):
        """
        Sends audio bytes to the Media AI container for Whisper transcription.
        """
        try:
            # Prepare the file for upload
            # audio_file is likely bytes, so we wrap in BytesIO if needed
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

    def generate_audio(self, prompt, voice=None, **kwargs):
        """
        Sends text to the Media AI container for TTS.
        """
        voice = voice or random.choice(list(self.VOICES.keys()))

        try:
            payload = {"text": prompt, "voice": voice}
            response = requests.post(f"{self._media_url}/tts", json=payload)
            response.raise_for_status()

            # Response content is WAV bytes
            wav_bytes = response.content

            # Convert to MP3 to match your original interface (using pydub)
            audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            mp3_buffer = io.BytesIO()
            audio.export(mp3_buffer, format="mp3")
            return mp3_buffer.getvalue()

        except Exception as e:
            log(f"TTS Error: {e}", _print=True)
            return None

    def generate_image(self, prompt, **kwargs):
        """
        Generates an image using Local AI.
        If 'files' are provided, performs Image-to-Image generation using the first file as reference.
        """
        try:
            # Prepare the multipart data
            # We send the prompt as a form field
            data = {"prompt": prompt}
            files = {}

            # Check if reference images were passed
            if kwargs.get("files"):
                # Take the first available file
                for fn, f_bytes in kwargs.get("files").items():
                    # If f_bytes is bytes, wrap in IO, else assume it's file-like
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes

                    # Add to the request files
                    # Key must be 'file' to match server.py logic
                    files["file"] = (fn, file_obj, "image/png")
                    break  # We only support 1 reference image for SD Img2Img

            # Send Request
            if files:
                # Multipart/form-data request (Prompt + File)
                response = requests.post(
                    f"{self._media_url}/generate-image", data=data, files=files
                )
            else:
                # Standard request (Prompt only) - server.py handles request.form vs json
                # But our updated server expects form data for consistency
                response = requests.post(f"{self._media_url}/generate-image", data=data)

            response.raise_for_status()

            # Returns WebP bytes directly
            return response.content

        except Exception as e:
            log(f"Image Gen Error: {e}", _print=True)
            return None

    def list_voices(self, filters=[]):
        # Same logic as before
        if not filters:
            return list(self.VOICES.keys())
        voices = []
        for voice, attribs in self.VOICES.items():
            if any(f.lower() in attribs for f in filters):
                voices.append(voice)
        return voices

    # Unused methods from original that don't apply to Local AI
    def upload(self, file):
        # Local models don't really have a "File Store" API like Gemini.
        # We handle context by passing text directly in prompt.
        pass
