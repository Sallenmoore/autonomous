from autonomous import log
from autonomous.model.autoattr import ReferenceAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


class OAIAgent(AutoModel):
    client_model = ReferenceAttr(choices=[OpenAIModel])
    _ai_model = OpenAIModel

    @property
    def client(self):
        if self.client_model is None:
            self.client_model = self._ai_model()
            self.save()
        return self.client_model

    def clear_files(self, file_id=None):
        return self.client.clear_files(file_id)

    def attach_file(self, file_contents, filename="dbdata.json"):
        return self.client.attach_file(file_contents, filename)

    def generate(self, messages, function=None, additional_instructions=""):
        if function is None:
            return self.client.generate_text(messages, additional_instructions)
        else:
            return self.client.generate_json(
                messages, function, additional_instructions
            )

    def generate_audio(self, prompt, file_path, **kwargs):
        return self.client.generate_audio(self, file_path, **kwargs)

    def generate_image(self, prompt, **kwargs):
        return self.client.generate_image(prompt, **kwargs)

    def summarize_text(self, text, primer=""):
        return self.client.generate_image(text, primer)
