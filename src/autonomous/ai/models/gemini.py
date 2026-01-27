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

    # Model definitions
    _text_model = "gemini-1.5-pro"
    _summary_model = "gemini-1.5-flash"
    _json_model = "gemini-1.5-pro"
    _stt_model = "gemini-1.5-pro"
    _image_model = "gemini-3-pro-image-preview"
    _tts_model = "gemini-2.0-flash-exp"

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

    SAFETY_SETTINGS = [
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_CIVIC_INTEGRITY",
            threshold="BLOCK_NONE",
        ),
    ]

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
            self._client = genai.Client(api_key=os.environ.get("GOOGLEAI_KEY"))
        return self._client

    def _add_function(self, user_function):
        tool_schema = {
            "name": user_function.get("name"),
            "description": user_function.get("description"),
            "parameters": user_function.get("parameters"),
        }
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
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(rate)
            wav_file.writeframes(raw_audio_bytes)
        buffer.seek(0)
        return buffer

    def _add_context(self, context):
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
                self.client.files.delete(name=fn)
            except Exception:
                pass

            file_content = f["file"]
            fileobj = (
                io.BytesIO(file_content)
                if isinstance(file_content, bytes)
                else file_content
            )

            uploaded_file = self.client.files.upload(
                file=fileobj,
                config={"mime_type": mime_type, "display_name": fn},
            )
            uploaded_files.append(uploaded_file)

            while uploaded_file.state.name == "PROCESSING":
                time.sleep(0.5)
                uploaded_file = self.client.get_file(uploaded_file.name)

        self.file_refs = [f.name for f in self.client.files.list()]
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
            contents.append(Part.from_uri(file_uri=uri, mime_type="application/json"))
            additional_instructions += "\nUse the provided uri file for reference\n"

        response = self.client.models.generate_content(
            model=self._json_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
                tools=[types.Tool(function_declarations=[function_definition])],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="ANY")
                ),
            ),
        )

        try:
            if not response.candidates or not response.candidates[0].content.parts:
                return {}

            tool_call = response.candidates[0].content.parts[0].function_call
            if tool_call and tool_call.name == function["name"]:
                return tool_call.args
            else:
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
            contents.append(Part.from_uri(file_uri=uri, mime_type="application/json"))

        response = self.client.models.generate_content(
            model=self._text_model,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.instructions}.{additional_instructions}",
            ),
            contents=contents,
        )
        return response.text

    def summarize_text(self, text, primer=""):
        primer = primer or self.instructions
        updated_prompt_list = []
        words = re.findall(r"\w+", text)

        for i in range(0, len(words), self.MAX_SUMMARY_TOKEN_LENGTH):
            updated_prompt_list.append(
                " ".join(words[i : i + self.MAX_SUMMARY_TOKEN_LENGTH])
            )

        full_summary = ""
        for p in updated_prompt_list:
            response = self.client.models.generate_content(
                model=self._summary_model,
                config=types.GenerateContentConfig(system_instruction=f"{primer}"),
                contents=p,
            )
            try:
                summary = response.candidates[0].content.parts[0].text
                full_summary += summary + "\n"
            except Exception as e:
                log(f"Summary Error: {e}", _print=True)
                break
        return full_summary

    def generate_transcription(
        self, audio_file, prompt="Transcribe this audio clip", display_name="audio.mp3"
    ):
        myfile = self.client.files.upload(
            file=io.BytesIO(audio_file),
            config={"mime_type": "audio/mp3", "display_name": display_name},
        )
        response = self.client.models.generate_content(
            model=self._stt_model,
            contents=[prompt, myfile],
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
                                voice_name=voice
                            )
                        )
                    ),
                ),
            )
            blob = response.candidates[0].content.parts[0].inline_data
            wav_buffer = self._create_wav_header(blob.data)
            audio_segment = AudioSegment.from_file(wav_buffer, format="wav")
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3")
            return mp3_buffer.getvalue()
        except Exception as e:
            log(f"==== Audio Gen Error: {e} ====", _print=True)
            raise e

    def _get_image_config(self, aspect_ratio_input):
        """
        Parses custom aspect ratio keys (e.g., '2KPortrait') into valid
        Google Gemini API parameters for ratio and size.
        """
        # Default fallback
        ratio = "1:1"
        size = "1K"

        # Logic Mapping
        # Keys match what your App sends in ttrpgbase.py
        if aspect_ratio_input == "2KPortrait":
            ratio = "3:4"
            size = "2K"  # <--- THIS WAS MISSING BEFORE
        elif aspect_ratio_input == "Portrait":
            ratio = "3:4"
            size = "2K"
        elif aspect_ratio_input == "Landscape":
            ratio = "16:9"
            size = "2K"
        elif aspect_ratio_input == "4K":
            ratio = "16:9"
            size = "4K"
        elif aspect_ratio_input == "4KPortrait":
            ratio = "3:4"
            size = "4K"
        elif aspect_ratio_input == "2K":
            ratio = "16:9"
            size = "2K"

        # Pass-through for standard inputs
        elif aspect_ratio_input in ["1:1", "3:4", "4:3", "9:16", "16:9"]:
            ratio = aspect_ratio_input

        return ratio, size

    def generate_image(self, prompt, negative_prompt="", files=None, aspect_ratio="2K"):
        image = None
        contents = [prompt]

        if files:
            filerefs = self._add_files(files, mime_type="image/webp")
            contents.extend(filerefs)

        try:
            # 1. Resolve Aspect Ratio AND Size
            valid_ratio, valid_size = self._get_image_config(aspect_ratio)

            # 2. Call API with correct parameters
            response = self.client.models.generate_content(
                model=self._image_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    safety_settings=self.SAFETY_SETTINGS,
                    image_config=types.ImageConfig(
                        aspect_ratio=valid_ratio,
                        image_size=valid_size,  # Now passing "2K" or "4K" correctly
                    ),
                ),
            )

            # 3. Extract Image Data
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        image = part.inline_data.data
                        break

            if not image:
                raise ValueError(
                    f"API returned Success but no image data found. Response: {response}"
                )

        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}", _print=True)
            raise e

        return image
