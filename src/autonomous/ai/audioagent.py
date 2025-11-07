from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import ReferenceAttr, StringAttr

from .models.openai import OpenAIModel


class AudioAgent(BaseAgent):
    name = StringAttr(default="audioagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    def generate(self, prompt, **kwargs):
        return self.get_client().generate_audio(prompt, **kwargs)

    ## DEPRECATED - use transcribe instead
    def generate_text(self, audio, **kwargs):
        log("AudioAgent.generate_text is deprecated; use transcribe instead.")
        return self.get_client().generate_audio_text(audio, **kwargs)

    def transcribe(self, audio, **kwargs):
        return self.get_client().generate_audio_text(audio, **kwargs)
