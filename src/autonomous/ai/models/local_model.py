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
    _ollama_url = os.environ.get("OLLAMA_API_BASE", "http://ollama_internal:11434/api")
    _media_url = os.environ.get("MEDIA_API_BASE", "http://media_ai_internal:5005")
    _text_model = "mistral-nemo"
    _json_model = "mistral-nemo"

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
        """
        Ollama doesn't support 'tools' strictly yet.
        We convert the tool definition into a system prompt instruction.
        """
        # If the user passes a raw dictionary (like a Gemini tool definition)
        # we extract the relevant parts for the schema.
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
        """
        Builds context based on RELATIONAL ASSOCIATIONS + SEMANTIC LORE.
        """

        # 1. Create a Cache Key based on what defines the "Scene"
        # We assume 'focus_object_id' + rough prompt length captures the context enough
        cache_key = f"ctx:{focus_object_id}:{len(prompt) // 50}"

        # 2. Check Cache
        cached_ctx = self._redis.get(cache_key)
        if cached_ctx:
            return cached_ctx

        context_str = ""

        # --- PART 1: MONGODB (Relational Associations) ---
        # If we are focusing on a specific object, fetch it and its specific refs.
        if focus_object_id:
            try:
                # 1. Fetch the Main Object
                # Handle both string ID and ObjectId
                oid = (
                    ObjectId(focus_object_id)
                    if isinstance(focus_object_id, str)
                    else focus_object_id
                )

                main_obj = self._mongo_db.objects.find_one({"_id": oid})

                if main_obj:
                    # Start the context with the main object itself
                    context_str += "### FOCUS OBJECT ###\n"
                    context_str += prompt

                    # 2. Extract References (Associations)
                    # 1. Start with the main list
                    ref_ids = main_obj.get("associations", []) or []

                    # 2. Safely add single fields (if they exist)
                    if world_id := main_obj.get("world"):
                        ref_ids.append(world_id)

                    # 3. Safely add lists (ensure they are lists)
                    ref_ids.extend(main_obj.get("stories", []) or [])
                    ref_ids.extend(main_obj.get("events", []) or [])

                    if ref_ids:
                        # Convert all to ObjectIds if they are strings
                        valid_oids = []
                        for rid in ref_ids:
                            try:
                                valid_oids.append(
                                    ObjectId(rid) if isinstance(rid, str) else rid
                                )
                            except:
                                pass

                        # 3. Fetch all associated objects in ONE query
                        if valid_oids:
                            associated_objs = self._mongo_db.objects.find(
                                {"_id": {"$in": valid_oids}}
                            )

                            context_str += "\n### ASSOCIATED REFERENCES ###\n"
                            for obj in associated_objs:
                                log(f"Associated Obj: {obj}", _print=True)
                                context_str += f"- {obj}\n"

                    context_str += "\n"
            except Exception as e:
                log(f"Mongo Association Error: {e}", _print=True)

        # --- PART 2: REDIS (Semantic Search) ---
        # We keep this! It catches "Lore" or "Rules" that aren't explicitly linked in the DB.
        # e.g., If the sword is "Elven", this finds "Elven History" even if not linked by ID.
        if len(prompt) > 10:
            vector = self.get_embedding(prompt)
            if vector:
                try:
                    q = "*=>[KNN 2 @vector $blob AS score]"  # Lowered to 2 to save tokens
                    params = {"blob": np.array(vector, dtype=np.float32).tobytes()}
                    results = self._redis.ft("search_index").search(
                        q, query_params=params
                    )

                    if results.docs:
                        context_str += "### RELEVANT LORE ###\n"
                        for doc in results.docs:
                            context_str += f"- {doc.content}\n"
                except Exception as e:
                    pass

        # 3. Save to Cache (Expire in 60s)
        # This prevents hammering the DB/Vector engine during a rapid conversation
        self._redis.set(cache_key, context_str, ex=120)

        return context_str

    def generate_json(self, message, function, additional_instructions="", **kwargs):
        """
        Mimics Gemini's tool use by forcing Ollama into JSON mode
        and injecting the schema into the prompt.
        """
        schema_str = self._convert_tools_to_json_schema(function)

        focus_pk = kwargs.get("focus_object")

        # Build Relational Context
        world_context = self.build_hybrid_context(message, focus_object_id=focus_pk)

        # Construct System Prompt
        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must respond strictly with a valid JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"Do not include markdown formatting or explanations."
            f"You must strictly adhere to the following context:\n"
            f"{world_context}"
        )

        payload = {
            "model": self._json_model,
            "prompt": message,
            "system": full_system_prompt,
            "format": "json",  # Force JSON mode
            "stream": False,
            "keep_alive": "24h",
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
        focus_pk = kwargs.get("focus_object")

        # Build Relational Context
        world_context = self.build_hybrid_context(message, focus_object_id=focus_pk)

        # Construct System Prompt
        full_system_prompt = (
            f"{self.instructions}. {additional_instructions}\n"
            f"You must strictly adhere to the following context:\n"
            f"{world_context}"
        )

        payload = {
            "model": self._text_model,
            "prompt": message,
            "system": full_system_prompt,
            "stream": False,
            "keep_alive": "24h",
        }

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
                "keep_alive": "24h",
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

    def generate_image(self, prompt, negative_prompt="", **kwargs):
        """
        Generates an image using Local AI.
        If 'files' are provided, performs Image-to-Image generation using the first file as reference.
        """
        try:
            # Prepare the multipart data
            # We send the prompt as a form field
            data = {"prompt": prompt, "negative_prompt": negative_prompt}
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
                    # TODO: Support multiple images if needed
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
