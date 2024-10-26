from autonomous import log
from autonomous.model.autoattr import ReferenceAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


class BaseAgent(AutoModel):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}

    client = ReferenceAttr(choices=[OpenAIModel])

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


#     def clear_files(self, file_id=None):
#         return self.client.clear_files(file_id)

#     def attach_file(self, file_contents, filename="dbdata.json"):
#         return self.client.attach_file(file_contents, filename)
