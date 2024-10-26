from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.ai.baseagent import BaseAgent

from .models.openai import OpenAIModel


class AudioAgent(BaseAgent):
    name = StringAttr(default="audioagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    def generate(self, prompt, file_path, **kwargs):
        return self.get_client().generate_audio(prompt, file_path, **kwargs)
