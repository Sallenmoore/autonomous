# from .agents.autogen import AutoGenAgent
# from .agents.local import LocalAIAgent
from .agents.mockai import MockAIAgent
from .agents.openai import OpenAIAgent


class AutoTeam:
    def __init__(self, model=None):
        self.proxy = None
        # if model == "autogen":
        #     self.proxy = AutoGenAgent()
        # if model == "local":
        #     self.proxy = LocalAIAgent()
        if model == "openai":
            self.proxy = OpenAIAgent()
        if not self.proxy:
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
