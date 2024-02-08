# from .agents.autogen import AutoGenAgent
# from .agents.local import LocalAIAgent
import os

from .agents.mockai import MockAIAgent
from .agents.openai import OpenAIAgent


class AutoTeam:
    def __init__(self, model=None):
        if model:
            self.proxy = model()
        else:
            model = os.getenv("AI_AGENT", "openai")
            self.proxy = None
            if model == "openai":
                self.proxy = OpenAIAgent()
            elif model == "mockai":
                self.proxy = MockAIAgent()
            else:
                raise Exception("Invalid model")

    def generate_audio(self, prompt, **kwargs):
        return self.proxy.generate_audio(prompt, **kwargs)

    def generate_image(self, prompt, **kwargs):
        return self.proxy.generate_image(prompt, **kwargs)

    def generate_json(
        self,
        text,
        functions,
        name="json_agent",
        primer_text="",
        file_data=None,
        context=[],
    ):
        return self.proxy.generate_json(
            text,
            functions,
            name=name,
            primer_text=primer_text,
            file_data=file_data,
            context=context,
        )

    def generate_text(
        self, text, name="json_agent", primer_text="", file=None, context=[]
    ):
        return self.proxy.generate_text(
            text, name=name, primer_text=primer_text, file_data=file, context=context
        )

    def summarize_text(self, text, primer=""):
        return self.proxy.summarize_text(text, primer)
