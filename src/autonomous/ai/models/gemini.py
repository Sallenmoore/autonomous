import io
import json
import os
import random

from google import genai
from google.genai import types

from autonomous import log
from autonomous.model.autoattr import DictAttr, ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class GeminiAIModel(AutoModel):
    _client = None
    _text_model = "gemini-2.5-pro"
    _summary_model = "gemini-2.5-flash"
    _image_model = "imagen-4.0-generate-001"
    _json_model = "gemini-2.5-pro"
    _audio_model = "gemini-2.5-flash-preview"
    _tts_model = "gemini-2.5-flash-preview-tts"
    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with various tasks."
    )

    @property
    def client(self):
        if not self._client:
            self._client = genai.Client(api_key=os.environ.get("GOOGLEAI_KEY"))
        return self._client

    def _add_function(self, user_function):
        user_function["strict"] = True
        user_function["parameters"]["additionalProperties"] = False
        if not user_function["parameters"].get("required"):
            user_function["parameters"]["required"] = list(
                user_function["parameters"]["properties"].keys()
            )
        return user_function

    def generate_json(self, message, function, additional_instructions=""):
        function = self._add_function(function)
        response = self.client.models.generate_content(
            model=self._json_model,
            contents=message,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": function,
                "system_instruction": f"{self.instructions}.{additional_instructions}",
            },
        )
        results = response.text
        try:
            results = json.loads(results, strict=False)
        except Exception:
            log(f"==== Invalid JSON:\n{results}", _print=True)
            return {}
        else:
            # log(f"==== Results: {results}", _print=True)
            # log("=================== END REPORT ===================", _print=True)
            return results

    def generate_text(self, message, additional_instructions=""):
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
            ),
            contents=message,
        )

        # log(results, _print=True)
        # log("=================== END REPORT ===================", _print=True)
        return response.text

    def generate_audio(self, prompt, **kwargs):
        voice = kwargs.get("voice") or random.choice(
            [
                "Zephyr",
                "Puck",
                "Charon",
                "Kore",
                "Fenrir",
                "Leda",
                "Orus",
                "Aoede",
                "Callirhoe",
                "Autonoe",
                "Enceladus",
                "Iapetus",
                "Umbriel",
                "Algieba",
                "Despina",
                "Erinome",
                "Algenib",
                "Rasalgethi",
                "Laomedeia",
                "Achernar",
                "Alnilam",
                "Schedar",
                "Gacrux",
                "Pulcherrima",
                "Achird",
                "Zubenelgenubi",
                "Vindemiatrix",
                "Sadachbia",
                "Sadaltager",
                "Sulafar",
            ]
        )

        response = self.client.models.generate_content(
            model=self._tts_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    )
                ),
            ),
        )
        blob = response.candidates[0].content.parts[0].inline_data
        # log(response, _print=True)
        return blob

    def generate_audio_text(self, audio_file, **kwargs):
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                "Transcribe this audio clip",
                types.Part.from_bytes(
                    data=audio_file,
                    mime_type="audio/mp3",
                ),
            ],
        )
        return response.text

    def generate_image(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.models.generate_content(
                model=self._image_model,
                contents=[prompt],
            )
            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]
            image = io.BytesIO(image_parts[0] if image_parts else None)
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}", _print=True)
            raise e
        return image

    def summarize_text(self, text, primer=""):
        response = self.client.models.generate_content(
            model=self._summary_model,
            config=types.GenerateContentConfig(
                system_instruction=f"You are a highly skilled AI trained in language comprehension and summarization.{primer}",
            ),
            contents=text,
        )
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
