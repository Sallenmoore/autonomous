from autonomous import log
from autonomous.model.autoattr import ReferenceAttr
from autonomous.model.automodel import AutoModel

from .models.openai import OpenAIModel


def clear_agents():
    for agent in OpenAIModel.all():
        log(f"Deleting {agent.name}")
        agent.clear_agents()
        agent.clear_files()
        agent.delete()
    return "Success"


class BaseAgent(AutoModel):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}

    client = ReferenceAttr(choices=[OpenAIModel])

    _ai_model = OpenAIModel

    def delete(self):
        if self.client:
            self.client.delete()
        return super().delete()

    def get_agent_id(self):
        return self.get_client().id

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

    def clear_files(self, file_id=None):
        return self.client.clear_files(file_id)

    def attach_file(self, file_contents, filename="dbdata.json"):
        return self.client.attach_file(file_contents, filename)
