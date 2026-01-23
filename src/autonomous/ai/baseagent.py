from autonomous import log
from autonomous.model.autoattr import ReferenceAttr
from autonomous.model.automodel import AutoModel

from .models.gemini import GeminiAIModel
from .models.local_model import LocalAIModel
from .models.openai import OpenAIModel


class BaseAgent(AutoModel):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}

    client = ReferenceAttr(choices=[LocalAIModel])

    _ai_model = LocalAIModel

    def delete(self):
        if self.client:
            self.client.delete()
        return super().delete()

    def get_agent_id(self):
        return self.get_client().id

    def get_client(self):
        self.client = self._ai_model(
            name=self.name,
            instructions=self.instructions,
            description=self.description,
        )
        self.client.save()
        self.save()
        return self.client
