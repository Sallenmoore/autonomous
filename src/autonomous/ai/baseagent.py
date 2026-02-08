from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel

from .models.gemini import GeminiAIModel
from .models.local_model import LocalAIModel


class BaseAgent(AutoModel):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}

    # 2. Map string names to classes
    MODEL_REGISTRY = {
        "local": LocalAIModel,
        "gemini": GeminiAIModel,
    }

    # 3. Allow client to be ANY of the supported models
    client = ReferenceAttr(choices=[LocalAIModel, GeminiAIModel])

    # 4. Add a provider field (default to local, can be overridden per agent)
    provider = StringAttr(default="gemini")

    def delete(self):
        if self.client:
            self.client.delete()
        return super().delete()

    def get_agent_id(self):
        return self.get_client().id

    def get_client(self, provider=None):
        # 5. Determine which class to use based on the provider string
        model_class = self.MODEL_REGISTRY.get(provider or self.provider, LocalAIModel)
        # If we already have a client, but it's the WRONG type (e.g. we switched providers), we might want to re-instantiate. For simplicity, we check if it exists first.
        if not isinstance(self.client, model_class):
            if self.client:
                log(
                    f"Re-instantiating client for agent {self.name} from {type(self.client).__name__} to {model_class.__name__}"
                )
                self.client.delete()
            self.client = model_class(
                name=self.name,
                instructions=self.instructions,
                description=self.description,
            )
            self.client.save()
            self.save()

        return self.client

    def add_to_job_meta(self, k, v):
        if job := AutoTasks.get_current_task():
            job.meta(k, v)

