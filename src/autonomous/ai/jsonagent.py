import json

from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.ai.baseagent import BaseAgent
from .models.openai import OpenAIModel


class JSONAgent(BaseAgent):
    name = StringAttr(default="jsonagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating JSON formatted data."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating JSON formatted data."
    )

    def clear_files(self, file_id=None):
        return self.get_client().clear_files(file_id)

    def attach_file(self, file_contents, filename="dbdata.json"):
        return self.get_client().attach_file(file_contents, filename)

    def generate(self, messages, function, additional_instructions=""):
        result = self.get_client().generate_json(
            messages, function, additional_instructions
        )
        if isinstance(result, str):
            result = json.loads(result)
        elif not isinstance(result, dict):
            raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        return result
