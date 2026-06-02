from autonomous import log
from autonomous.model.autoattr import ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.taskrunner.autotasks import AutoTasks

from .models.flux import FluxAIModel
from .models.gemini import GeminiAIModel
from .models.local_model import LocalAIModel
from .models.mock_model import MockAIModel
from .models.openai_compat import OpenAIClient


class BaseAgent(AutoModel):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}

    # 2. Map string names to classes
    MODEL_REGISTRY = {
        "local": LocalAIModel,
        "gemini": GeminiAIModel,
        "openai": OpenAIClient,
        "mock": MockAIModel,
        "flux": FluxAIModel,
    }

    # 3. Allow client to be ANY of the supported models
    client = ReferenceAttr(
        choices=[LocalAIModel, GeminiAIModel, OpenAIClient, MockAIModel, FluxAIModel]
    )

    # 4. Add a provider field (default to local, can be overridden per agent)
    provider = StringAttr(default="local")

    def delete(self):
        if self.client:
            self.client.delete()
        return super().delete()

    def get_agent_id(self):
        return self.get_client().id

    def get_client(self, provider=None, *, persist: bool = True):
        """Return the agent's client, instantiating the right provider on demand.

        Fast path: when ``self.client`` is already the correct
        ``MODEL_REGISTRY[provider]`` type, returns it directly with no
        DB I/O.

        Slow path (provider changed): with ``persist=True`` (default,
        legacy behavior) deletes the old client doc, constructs a
        fresh one, then saves both the new client and ``self`` so the
        reference is durable. With ``persist=False`` no DB I/O fires
        at all — the old client doc is NOT deleted (it becomes
        orphaned in the database) and the new client is in-memory
        only.

        Args:
            persist: When ``False``, skip ALL DB writes on the
                provider-switch path — including the old client's
                ``delete()``. The old doc remains as an orphan in the
                database until a subsequent ``persist=True`` call (or
                manual cleanup) reclaims it. This is intentional: a
                delete-without-save would leave ``self.client``
                pointing at a destroyed doc, and the asymmetry of
                "no writes by default" is more useful than partial
                writes. Use ``persist=False`` for test setup or
                throughput-sensitive request-scoped instantiation
                where the caller takes responsibility for the next
                ``save()`` on the agent.
        """
        # 5. Determine which class to use based on the provider string
        model_class = self.MODEL_REGISTRY.get(provider or self.provider, LocalAIModel)
        # If we already have a client, but it's the WRONG type (e.g. we switched providers), we might want to re-instantiate. For simplicity, we check if it exists first.
        if not isinstance(self.client, model_class):
            if self.client:
                # Always log the re-instantiation — the operator's
                # attribution signal for "when did the agent switch
                # provider?". Pre-#79 this lived inside `and persist:`,
                # so persist=False switches produced no log AND no
                # Mongo trace, leaving zero evidence of the swap.
                log(
                    f"Re-instantiating client for agent {self.name} "
                    f"from {type(self.client).__name__} to "
                    f"{model_class.__name__}"
                    + ("" if persist else " (persist=False: old doc orphaned)")
                )
                if persist:
                    # Only delete the old client doc when we're
                    # persisting the new one. Otherwise we'd leave
                    # self.client pointing at a destroyed doc —
                    # worse than leaking an orphan that a future
                    # persist=True call can reclaim.
                    self.client.delete()
            self.client = model_class(
                name=self.name,
                instructions=self.instructions,
                description=self.description,
            )
            if persist:
                self.client.save()
                self.save()

        return self.client

    def add_to_job_meta(self, k, v):
        if job := AutoTasks().get_current_task():
            job.meta(k, v)
