import os

from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr
from autonomous.ai._credentials import client_key_scope


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

    def summarize_text(self, text, primer="", model=None, api_key=None):
        # `model` (#173) overrides the role-default summary model
        # (provider-specific: `_summary_model` on openai_compat/gemini,
        # `_text_model` on local). `None` keeps env behavior unchanged.
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        client = self.get_client(
            os.environ.get("SUMMARY_AI_AGENT", self.provider)
        )
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
    ):
        # `temperature` stays conditional because adapters have heterogeneous
        # defaults (local/openai_compat=0.7; gemini/mock=None) and forwarding
        # an explicit None would override their defaults. `system_prompt` and
        # `model` are uniform — every adapter defaults them to None meaning
        # "no override" — so they ride as direct kwargs.
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        # BYOK (#227): ``api_key`` overrides this provider's credential
        # for THIS call only — bound to a ContextVar, so concurrent jobs
        # in the same worker never see each other's keys, and nothing is
        # persisted on the agent.
        client = self.get_client(os.environ.get("TEXT_AI_AGENT", self.provider))
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
