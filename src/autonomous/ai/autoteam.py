from .agents.autogen import AutoGenAgent
from .agents.local import LocalAIAgent
from .agents.openai import OpenAIAgent
from .agents.mockai import MockAIAgent


class AutoTeam:
    def __init__(self, model=None):
        if model == "autogen":
            self.proxy = AutoGenAgent()
        elif model == "local":
            self.proxy = LocalAIAgent()
        elif model == "openai":
            self.proxy = OpenAIAgent()
        else:
            self.proxy = MockAIAgent()

    def generate_image(self, prompt, **kwargs):
        return self.proxy.generate_image(prompt, **kwargs)

    def generate_json(
        self,
        text,
        functions,
        primer_text="",
    ):
        return self.proxy.generate_json(text, functions, primer_text)

    def generate_text(self, text, primer_text=""):
        return self.proxy.generate_text(text, primer_text)

    def summarize_text(self, text, primer=""):
        return self.proxy.summarize_text(text, primer)
