from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


class AudioAgent(AutoModel):
    client = ReferenceAttr(choices=[OpenAIModel])
    name = StringAttr(default="audioagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating audio files."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating audio files."
    )

    _ai_model = OpenAIModel

    def get_client(self):
        if self.client is None:
            self.client = self._ai_model(
                name=self.name,
                instructions=self.instructions,
                description=self.description,
            )
            self.client.save()
            self.save()
        return self.client

    def generate(self, prompt, file_path, **kwargs):
        return self.get_client().generate_audio(prompt, file_path, **kwargs)
