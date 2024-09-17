from autonomous import log
from autonomous.model.autoattr import ReferenceAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


# class BaseAgent(AutoModel):
#     client_model = ReferenceAttr(choices=[OpenAIModel])
#     _ai_model = OpenAIModel

#     @property
#     def client(self):
#         if self.client_model is None:
#             self.client_model = self._ai_model()
#             self.save()
#         return self.client_model

#     def clear_files(self, file_id=None):
#         return self.client.clear_files(file_id)

#     def attach_file(self, file_contents, filename="dbdata.json"):
#         return self.client.attach_file(file_contents, filename)
