import io
import json
import os
import random
import re
import time
import wave

from google import genai
from google.genai import types
from google.genai.types import Part
from pydub import AudioSegment

from autonomous import log
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class GeminiAIModel(AutoModel):
    _client = None
    _text_model = "gemini-3-pro-preview"
    _summary_model = "gemini-2.5-flash"
    _image_model = "gemini-3-pro-image-preview"
    _json_model = "gemini-3-pro-preview"
    _stt_model = "gemini-3-pro-preview"
    _tts_model = "gemini-2.5-flash-preview-tts"

    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="agent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with various tasks."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with various tasks."
    )
    file_refs = ListAttr(StringAttr(default=[]))

    MAX_FILES = 14
    MAX_SUMMARY_TOKEN_LENGTH = 10000
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

    @property
    def client(self):
        if not self._client:
            # log("=== Initializing Gemini AI Client ===", _print=True)
            self._client = genai.Client(api_key=os.environ.get("GOOGLEAI_KEY"))
            # log("=== Gemini AI Client Initialized ===", _print=True)
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

    def _add_context(self, context):
        # Create in-memory file
        context_data = (
            json.dumps(context, indent=2) if isinstance(context, dict) else str(context)
        )

        f = io.BytesIO(context_data.encode("utf-8"))
        f.name = f"context-{self.pk}"
        return self._add_files([{"name": f.name, "file": f}])

    def _add_files(self, file_list, mime_type="application/json"):
        uploaded_files = []
        for f in file_list[: self.MAX_FILES]:
            fn = f["name"]
            try:
                result = self.client.files.delete(name=fn)
            except Exception as e:
                pass
                # log(f"No existing file to delete for {fn}: {e}", _print=True)
            else:
                pass
                # log(f"Deleting old version of {fn}: {result}", _print=True)

            # If the content is raw bytes, wrap it in BytesIO
            file_content = f["file"]
            if isinstance(file_content, bytes):
                fileobj = io.BytesIO(file_content)
            else:
                fileobj = file_content
            uploaded_file = self.client.files.upload(
                file=fileobj,
                config={"mime_type": mime_type, "display_name": fn},
            )
            uploaded_files.append(uploaded_file)

            # This ensures the file is 'ACTIVE' before you use it in a prompt.
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(0.5)
                uploaded_file = self.client.get_file(uploaded_file.name)
        self.file_refs = [f.name for f in self.client.files.list()]  # Update file_refs
        self.save()
        return uploaded_files

    def generate_json(
        self, message, function, additional_instructions="", uri="", context={}
    ):
        function_definition = self._add_function(function)

        contents = [message]
        if context:
            contents.extend(self._add_context(context))
            additional_instructions += (
                f"\nUse the uploaded context file for reference: context-{self.pk}\n"
            )

        if uri:
            contents.append(
                Part.from_uri(
                    file_uri=uri,
                    mime_type="application/json",
                ),
            )
            additional_instructions += "\nUse the provided uri file for reference\n"

        response = self.client.models.generate_content(
            model=self._json_model,
            contents=contents,
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

    def generate_text(self, message, additional_instructions="", uri="", context={}):
        contents = [message]
        if context:
            contents.extend(self._add_context(context))
            additional_instructions += (
                f"\nUse the uploaded context file for reference: context-{self.pk}\n"
            )

        if uri:
            contents.append(
                Part.from_uri(
                    file_uri=uri,
                    mime_type="application/json",
                ),
            )

        response = self.client.models.generate_content(
            model=self._text_model,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
            ),
            contents=contents,
        )

        # log(results, _print=True)
        # log("=================== END REPORT ===================", _print=True)
        return response.text

    def summarize_text(self, text, primer=""):
        primer = primer or self.instructions

        updated_prompt_list = []
        # Find all words in the prompt
        words = re.findall(r"\w+", text)
        # Split the words into chunks
        for i in range(0, len(words), self.MAX_SUMMARY_TOKEN_LENGTH):
            # Join a chunk of words and add to the list
            updated_prompt_list.append(
                " ".join(words[i : i + self.MAX_SUMMARY_TOKEN_LENGTH])
            )

        full_summary = ""
        for p in updated_prompt_list:
            response = self.client.models.generate_content(
                model=self._summary_model,
                config=types.GenerateContentConfig(
                    system_instruction=f"{primer}",
                ),
                contents=text,
            )
            try:
                summary = response.candidates[0].content.parts[0].text
            except Exception as e:
                log(f"{type(e)}:{e}\n\n Unable to generate content ====", _print=True)
                break
            else:
                full_summary += summary + "\n"
        return summary

    def generate_transcription(
        self,
        audio_file,
        prompt="Transcribe this audio clip",
        display_name="audio.mp3",
    ):
        myfile = self.client.files.upload(
            file=io.BytesIO(audio_file),
            config={
                "mime_type": "audio/mp3",
                "display_name": display_name,
            },
        )

        response = self.client.models.generate_content(
            model=self._stt_model,
            contents=[
                prompt,
                myfile,
            ],
        )
        return response.text

    def list_voices(self, filters=[]):
        if not filters:
            return list(self.VOICES.keys())
        voices = []
        for voice, attribs in self.VOICES.items():
            if any(f.lower() in attribs for f in filters):
                voices.append(voice)
        return voices

    def generate_audio(self, prompt, voice=None):
        voice = voice or random.choice(self.list_voices())
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

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="3:4",
        image_size="2K",
    ):
        image = None
        contents = [prompt]

        if files:
            filerefs = self._add_files(files, mime_type="image/webp")
            contents.extend(filerefs)

        try:
            # log(self._image_model, contents, _print=True)
            response = self.client.models.generate_content(
                model=self._image_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    safety_settings=[
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                    ],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )
            log(response, _print=True)
            log(response.candidates, _print=True)
            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]
            image = image_parts[0]
        except Exception as e:
            log(
                f"==== Error: Unable to create image ====\n\n{e}",
                _print=True,
            )
            raise e
        return image
