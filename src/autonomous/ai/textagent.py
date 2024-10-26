from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.ai.baseagent import BaseAgent
from .models.openai import OpenAIModel


class TextAgent(BaseAgent):
    name = StringAttr(default="textagent")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating text according to the given requirements."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating text according to the given requirements."
    )

    def clear_files(self, file_id=None):
        return self.get_client().clear_files(file_id)

    def attach_file(self, file_contents, filename="dbdata.json"):
        return self.get_client().attach_file(file_contents, filename)

    def summarize_text(self, text, primer=""):
        return self.get_client().summarize_text(text, primer)

    def generate(self, messages, additional_instructions=""):
        return self.get_client().generate_text(messages, additional_instructions)
