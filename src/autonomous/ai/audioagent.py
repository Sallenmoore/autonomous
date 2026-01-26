import os

from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class AudioAgent(BaseAgent):
    name = StringAttr(default="audioagent")

    provider = StringAttr(default="gemini")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    def generate(self, prompt, voice=None):
        return self.get_client(
            os.environ.get("TTS_AI_AGENT", self.provider)
        ).generate_audio(prompt, voice=voice)

    def transcribe(
        self, audio, prompt="Transcribe this audio clip", display_name="audio.mp3"
    ):
        return self.get_client(
            os.environ.get("TRANSCRIBE_AI_AGENT", self.provider)
        ).generate_transcription(
            audio,
            prompt=prompt,
        )

    def available_voices(self, filters=[]):
        return self.get_client().list_voices(filters=filters)
