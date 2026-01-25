import io
import json
import os
import random

import numpy as np
import pymongo
import redis
import requests
from bson.objectid import ObjectId
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
    _ollama_url = os.environ.get("OLLAMA_API_BASE_URL", "INVALID")
    _media_url = os.environ.get("MEDIA_API_BASE_URL", "INVALID")
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

    def generate_json(
        self, message, function, additional_instructions="", uri="", context={}
    ):
        schema_str = self._convert_tools_to_json_schema(function)
        # 1. Base System Prompt
        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must respond strictly with a valid JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"Do not include markdown formatting or explanations."
            f"You must strictly adhere to the following context:\n {json.dumps(context, indent=2)}"
            if context
            else f"Use the following URI for reference: {uri}"
            if uri
            else ""
        )

        # 3. Send to Ollama
        payload = {
            "model": self._json_model,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": message},
            ],
            "stream": False,
            "keep_alive": "24h",
        }

        try:
            print(
                f"==== {self._ollama_url}:  LocalAI JSON Payload: {json.dumps(payload, indent=2)} ===="
            )
            response = requests.post(f"{self._ollama_url}/chat", json=payload)
            response.raise_for_status()

            # FIX: Chat API returns 'message' -> 'content'
            result_text = response.json().get("message", {}).get("content", "{}")
            # If the tool returns a wrapper, unwrap it!
            result_dict = json.loads(result_text)
            if "parameters" in result_dict and isinstance(
                result_dict["parameters"], dict
            ):
                params = result_dict.pop("parameters")
                result_dict.update(params)
            return result_dict

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            return {}

    def generate_text(self, message, additional_instructions="", uri="", context={}):
        # 1. Base System Prompt
        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must strictly adhere to the following context:\n {json.dumps(context, indent=2)}"
            if context
            else f"Use the following URI for reference: {uri}"
            if uri
            else ""
        )

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
            # FIX: Chat API returns 'message' -> 'content'
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

    def generate_audio(self, prompt, voice=None):
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

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="3:4",
        image_size="2K",
    ):
        try:
            data = {"prompt": prompt, "negative_prompt": negative_prompt}
            img_files = {}
            if files:
                for fn, f_bytes in files.items():
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes
                    img_files["file"] = (fn, file_obj, "image/png")
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

    def list_voices(self, filters=[]):
        if not filters:
            return list(self.VOICES.keys())
        voices = []
        for voice, attribs in self.VOICES.items():
            if any(f.lower() in attribs for f in filters):
                voices.append(voice)
        return voices
