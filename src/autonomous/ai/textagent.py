from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr
from autonomous.ai._credentials import client_key_scope
from autonomous.ai._routing import resolve_client
from autonomous.ai.protocol import sampling_overrides


class TextAgent(BaseAgent):
    name = StringAttr(default="textagent")

    # Force this agent to use Gemini
    provider = StringAttr(default="local")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating text according to the given requirements."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating text according to the given requirements."
    )

    def summarize_text(
        self, text, primer="", model=None, api_key=None, provider=None
    ):
        # `model` (#173) overrides the role-default summary model
        # (provider-specific: `_summary_model` on openai_compat/gemini,
        # `_text_model` on local). `None` keeps env behavior unchanged.
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        # #239: ``provider`` overrides the env-derived provider for THIS
        # call only, on a transient client. Pairs with ``api_key`` —
        # this user's provider, billed to this user's key.
        client = resolve_client(self, provider, "SUMMARY_AI_AGENT")
        with client_key_scope(client, api_key):
            result = client.summarize_text(text, primer=primer, model=model)
        self.add_to_job_meta("Last SUMMARY", result)
        return result

    def generate(
        self,
        message,
        additional_instructions="",
        uri="",
        context="",
        temperature=None,
        system_prompt=None,
        model=None,
        api_key=None,
        provider=None,
        frequency_penalty=None,
        presence_penalty=None,
        top_p=None,
        seed=None,
    ):
        # `temperature` stays conditional because adapters have heterogeneous
        # defaults (local/openai_compat=0.7; gemini/mock=None) and forwarding
        # an explicit None would override their defaults. `system_prompt` and
        # `model` are uniform — every adapter defaults them to None meaning
        # "no override" — so they ride as direct kwargs.
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        # #248: same only-when-set rule as temperature.
        kwargs.update(sampling_overrides(frequency_penalty, presence_penalty, top_p, seed))
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        # #239: see summarize_text — per-call provider override.
        client = resolve_client(self, provider, "TEXT_AI_AGENT")
        with client_key_scope(client, api_key):
            result = client.generate_text(
                message,
                additional_instructions,
                uri=uri,
                context=context,
                system_prompt=system_prompt,
                model=model,
                **kwargs,
            )
        self.add_to_job_meta("Last TEXT", result)
        return result
