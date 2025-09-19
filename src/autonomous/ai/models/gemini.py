import io
import json
import os
import random
import wave

from google import genai
from google.genai import types
from pydub import AudioSegment

from autonomous import log
from autonomous.model.autoattr import DictAttr, ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class GeminiAIModel(AutoModel):
    _client = None
    _text_model = "gemini-2.5-pro"
    _summary_model = "gemini-2.5-flash"
    _image_model = "gemini-2.5-flash-image-preview"
    _json_model = "gemini-2.5-pro"
    _stt_model = "gemini-2.5-flash"
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
        # This function is now a bit more advanced to conform to the Tool Use schema
        tool_schema = {
            "name": user_function.get("name"),
            "description": user_function.get("description"),
            "parameters": user_function.get("parameters"),
        }

        # Validate that the schema has a name, description, and parameters
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
        """Creates an in-memory WAV file from raw PCM audio bytes."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            # Set audio parameters
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(rate)  # 16,000 Hz sample rate

            # Write the raw audio data
            wav_file.writeframes(raw_audio_bytes)

        buffer.seek(0)
        return buffer

    def generate_json(self, message, function, additional_instructions=""):
        # The API call must use the 'tools' parameter instead of 'response_json_schema'
        function_definition = self._add_function(function)

        response = self.client.models.generate_content(
            model=self._json_model,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
                tools=[types.Tool(function_declarations=[function_definition])],
                tool_config={
                    "function_calling_config": {
                        "mode": "ANY",  # Force a function call
                    }
                },
            ),
        )

        # The response is now a ToolCall, not a JSON string
        try:
            # log(response.candidates[0].content.parts[0].function_call, _print=True)
            tool_call = response.candidates[0].content.parts[0].function_call
            if tool_call and tool_call.name == function["name"]:
                return tool_call.args
            else:
                log(
                    "==== Model did not return a tool call or returned the wrong one. ===="
                )
                log(f"Response: {response.text}", _print=True)
                return {}
        except Exception as e:
            log(f"==== Failed to parse ToolCall response: {e} ====")
            return {}

    def generate_text(self, message, additional_instructions=""):
        response = self.client.models.generate_content(
            model=self._text_model,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
            ),
            contents=message,
        )

        # log(results, _print=True)
        # log("=================== END REPORT ===================", _print=True)
        return response.text

    def generate_audio_text(self, audio_file):
        response = self.client.models.generate_content(
            model=self._stt_model,
            contents=[
                "Transcribe this audio clip",
                types.Part.from_bytes(
                    data=audio_file,
                    mime_type="audio/mp3",
                ),
            ],
        )
        return response.text

    def generate_audio(self, prompt, voice=None):
        voice = voice or random.choice(
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

        try:
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

            # Create a WAV file in memory from the raw audio bytes
            wav_buffer = self._create_wav_header(blob.data)

            # 2. Load the WAV audio using pydub, which will now correctly read the header
            audio_segment = AudioSegment.from_file(wav_buffer, format="wav")

            # 3. Create a new in-memory buffer for the MP3 output
            mp3_buffer = io.BytesIO()

            # 4. Export the audio segment directly to the in-memory buffer
            audio_segment.export(mp3_buffer, format="mp3")

            # 5. Return the bytes from the buffer, not the filename
            return mp3_buffer.getvalue()

        except Exception as e:
            log(
                f"==== Error: Unable to generate audio ====\n{type(e)}:{e}", _print=True
            )
            # You can return a default empty byte string or re-raise the exception
            raise e

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
            # log(image_parts, _print=True)
            image = image_parts[0]
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}", _print=True)
            raise e
        return image

    def summarize_text(self, text, primer=""):
        primer = primer or self.instructions
        response = self.client.models.generate_content(
            model=self._summary_model,
            config=types.GenerateContentConfig(
                system_instruction=f"{primer}",
            ),
            contents=text,
        )
        log(response)
        try:
            result = response.candidates[0].content.parts[0].text
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return None

        return result
