import abc


class BaseAgent(abc.ABC):
    @abc.abstractmethod
    def generate_audio(self, prompt, **kwargs):
        pass

    @abc.abstractmethod
    def generate_image(self, prompt, **kwargs):
        pass

    @abc.abstractmethod
    def generate_json(
        self, text, functions, name="json_agent", primer_text="", file=None, context=[]
    ):
        pass

    @abc.abstractmethod
    def generate_text(
        self, text, name="text_agent", primer_text="", file=None, context=[]
    ):
        pass

    @abc.abstractmethod
    def summarize_text(self, text, primer_text=""):
        pass
