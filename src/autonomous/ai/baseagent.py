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

    # def get_embedding(self, text):
    #     """Helper to get embeddings for vector search"""
    #     try:
    #         res = requests.post(f"{self._media_url}/embeddings", json={"text": text})
    #         res.raise_for_status()
    #         return res.json()["embedding"]
    #     except Exception:
    #         return []

    # def gather_context(self, prompt, focus_object_id=None):
    #     """
    #     Retrieves context string from Mongo/Redis.
    #     Previously 'build_hybrid_context' in LocalAIModel.
    #     """
    #     context_str = ""

    #     # 1. Fetch from MongoDB (Focus Object)
    #     if focus_object_id:
    #         try:
    #             oid = (
    #                 ObjectId(focus_object_id)
    #                 if isinstance(focus_object_id, str)
    #                 else focus_object_id
    #             )
    #             if main_obj := self._mongo_db.objects.find_one({"_id": oid}):
    #                 context_str += f"### FOCUS OBJECT ###\n{main_obj}\n"
    #                 ref_ids = main_obj.get("associations", []) or []
    #                 if world_id := main_obj.get("world"):
    #                     ref_ids.append(world_id)
    #                 ref_ids.extend(main_obj.get("stories", []) or [])
    #                 ref_ids.extend(main_obj.get("events", []) or [])

    #                 if ref_ids:
    #                     valid_oids = [
    #                         ObjectId(rid) if isinstance(rid, str) else rid
    #                         for rid in ref_ids
    #                     ]
    #                     if valid_oids:
    #                         associated_objs = self._mongo_db.objects.find(
    #                             {"_id": {"$in": valid_oids}}
    #                         )
    #                         context_str += "\n### ASSOCIATED REFERENCES ###\n"
    #                         for obj in associated_objs:
    #                             context_str += f"- {obj}\n"
    #                 context_str += "\n"
    #         except Exception as e:
    #             print(f"Context Error: {e}")

    #     # 2. Fetch from Redis (Vector Search)
    #     if len(prompt) > 10:
    #         vector = self.get_embedding(prompt)
    #         if vector:
    #             try:
    #                 q = "*=>[KNN 2 @vector $blob AS score]"
    #                 params = {"blob": np.array(vector, dtype=np.float32).tobytes()}
    #                 results = self._redis.ft("search_index").search(
    #                     q, query_params=params
    #                 )
    #                 if results.docs:
    #                     context_str += "\n### RELEVANT LORE ###\n"
    #                     for doc in results.docs:
    #                         context_str += f"- {doc.content}\n"
    #             except Exception:
    #                 pass

    #     return context_str
