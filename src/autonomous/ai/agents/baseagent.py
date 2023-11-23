import abc


class BaseAgent(abc.ABC):
    @abc.abstractmethod
    def generate_image(self, prompt, **kwargs):
        pass

    @abc.abstractmethod
    def generate_json(
        self,
        text,
        functions,
        primer_text="",
    ):
        pass

    @abc.abstractmethod
    def generate_text(self, text, primer_text=""):
        pass

    @abc.abstractmethod
    def summarize_text(self, text, primer_text=""):
        pass
