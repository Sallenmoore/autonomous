from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


class TextAgent(AutoModel):
    client = ReferenceAttr(choices=[OpenAIModel])
    name = StringAttr(default="textagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating text according to the given requirements."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating text according to the given requirements."
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

    def summarize_text(self, text, primer=""):
        return self.get_client().summarize_text(text, primer)

    def generate(self, messages, additional_instructions=""):
        return self.get_client().generate_text(messages, additional_instructions)
