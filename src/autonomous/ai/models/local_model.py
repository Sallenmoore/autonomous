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
    _ollama_url = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434/api")
    _media_url = os.environ.get("MEDIA_API_BASE", "http://media_ai:5005")
    _text_model = "llama3"
    _json_model = "llama3"

    # DB Connections
    _mongo_client = pymongo.MongoClient("mongodb://db:27017/")
    _mongo_db = os.getenv("DB_DB", "default")
    _redis = redis.Redis(host="cachedb", port=6379, decode_responses=True)

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

    def get_embedding(self, text):
        try:
            res = requests.post(f"{self._media_url}/embeddings", json={"text": text})
            res.raise_for_status()
            return res.json()["embedding"]
        except Exception as e:
            log(f"Embedding Error: {e}", _print=True)
            return []

    def build_hybrid_context(self, prompt, focus_object_id=None):
        cache_key = f"ctx:{focus_object_id}:{len(prompt) // 50}"
        cached_ctx = self._redis.get(cache_key)
        if cached_ctx:
            return cached_ctx

        context_str = ""
        # --- PART 1: MONGODB ---
        if focus_object_id:
            try:
                oid = (
                    ObjectId(focus_object_id)
                    if isinstance(focus_object_id, str)
                    else focus_object_id
                )
                main_obj = self._mongo_db.objects.find_one({"_id": oid})

                if main_obj:
                    context_str += "### FOCUS OBJECT ###\n" + prompt
                    ref_ids = main_obj.get("associations", []) or []
                    if world_id := main_obj.get("world"):
                        ref_ids.append(world_id)
                    ref_ids.extend(main_obj.get("stories", []) or [])
                    ref_ids.extend(main_obj.get("events", []) or [])

                    if ref_ids:
                        valid_oids = [
                            ObjectId(rid) if isinstance(rid, str) else rid
                            for rid in ref_ids
                        ]
                        if valid_oids:
                            associated_objs = self._mongo_db.objects.find(
                                {"_id": {"$in": valid_oids}}
                            )
                            context_str += "\n### ASSOCIATED REFERENCES ###\n"
                            for obj in associated_objs:
                                context_str += f"- {obj}\n"
                    context_str += "\n"
            except Exception as e:
                log(f"Mongo Association Error: {e}", _print=True)

        # --- PART 2: REDIS ---
        if len(prompt) > 10:
            vector = self.get_embedding(prompt)
            if vector:
                try:
                    q = "*=>[KNN 2 @vector $blob AS score]"
                    params = {"blob": np.array(vector, dtype=np.float32).tobytes()}
                    results = self._redis.ft("search_index").search(
                        q, query_params=params
                    )
                    if results.docs:
                        context_str += "### RELEVANT LORE ###\n"
                        for doc in results.docs:
                            context_str += f"- {doc.content}\n"
                except Exception:
                    pass

        self._redis.set(cache_key, context_str, ex=120)
        return context_str

    def generate_json(self, message, function, additional_instructions="", **kwargs):
        """
        UPDATED: Uses correct /api/chat payload structure (messages list)
        """
        schema_str = self._convert_tools_to_json_schema(function)
        focus_pk = kwargs.get("focus_object")
        world_context = self.build_hybrid_context(message, focus_object_id=focus_pk)

        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must respond strictly with a valid JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"Do not include markdown formatting or explanations."
            f"You must strictly adhere to the following context:\n"
            f"{world_context}"
        )

        # FIX: Using 'messages' instead of 'prompt'/'system'
        payload = {
            "model": "llama3",
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": message},
            ],
            "format": "json",
            "stream": False,
            "keep_alive": "24h",
        }

        try:
            response = requests.post(f"{self._ollama_url}/chat", json=payload)
            response.raise_for_status()

            # FIX: Chat API returns 'message' -> 'content'
            result_text = response.json().get("message", {}).get("content", "{}")
            return json.loads(result_text)

        except Exception as e:
            log(f"==== LocalAI JSON Error: {e} ====", _print=True)
            return {}

    def generate_text(self, message, additional_instructions="", **kwargs):
        """
        UPDATED: Uses correct /api/chat payload structure
        """
        focus_pk = kwargs.get("focus_object")
        world_context = self.build_hybrid_context(message, focus_object_id=focus_pk)

        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must strictly adhere to the following context:\n"
            f"{world_context}"
        )

        payload = {
            "model": "llama3",
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

    def summarize_text(self, text, primer="", **kwargs):
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

    def generate_audio_text(self, audio_file, prompt="", **kwargs):
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

    def generate_audio(self, prompt, voice=None, **kwargs):
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

    def generate_image(self, prompt, negative_prompt="", **kwargs):
        try:
            data = {"prompt": prompt, "negative_prompt": negative_prompt}
            files = {}
            if kwargs.get("files"):
                for fn, f_bytes in kwargs.get("files").items():
                    if isinstance(f_bytes, bytes):
                        file_obj = io.BytesIO(f_bytes)
                    else:
                        file_obj = f_bytes
                    files["file"] = (fn, file_obj, "image/png")
                    break
            if files:
                response = requests.post(
                    f"{self._media_url}/generate-image", data=data, files=files
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
