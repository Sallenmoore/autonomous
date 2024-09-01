import json

from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


class JSONAgent(AutoModel):
    client = ReferenceAttr(choices=[OpenAIModel])
    name = StringAttr(default="jsonagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating JSON formatted data."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating JSON formatted data."
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

    def generate(self, messages, function, additional_instructions=""):
        result = self.get_client().generate_json(
            messages, function, additional_instructions
        )
        if isinstance(result, str):
            result = json.loads(result)
        elif not isinstance(result, dict):
            raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        return result
