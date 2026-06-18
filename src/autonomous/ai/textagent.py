import os

from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


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

    def summarize_text(self, text, primer=""):
        result = self.get_client(
            os.environ.get("SUMMARY_AI_AGENT", self.provider)
        ).summarize_text(text, primer=primer)
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
    ):
        # self.add_to_job_meta("prompt", message)
        # `temperature` stays conditional because adapters have heterogeneous
        # defaults (local/openai_compat=0.7; gemini/mock=None) and forwarding
        # an explicit None would override their defaults. `system_prompt` is
        # uniform across all four adapters (default None = "no override"), so
        # it rides as a direct kwarg.
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        result = self.get_client(
            os.environ.get("TEXT_AI_AGENT", self.provider)
        ).generate_text(
            message,
            additional_instructions,
            uri=uri,
            context=context,
            system_prompt=system_prompt,
            **kwargs,
        )
        self.add_to_job_meta("Last TEXT", result)
        return result
