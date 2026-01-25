import os

from autonomous import log
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class TextAgent(BaseAgent):
    name = StringAttr(default="textagent")

    # Force this agent to use Gemini
    provider = StringAttr(default="gemini")
    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating text according to the given requirements."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating text according to the given requirements."
    )

    def summarize_text(self, text, primer=""):
        return self.get_client(
            os.environ.get("SUMMARY_AI_AGENT", self.provider)
        ).summarize_text(text, primer=primer)

    def generate(self, message, additional_instructions="", uri="", context=""):
        return self.get_client(
            os.environ.get("TEXT_AI_AGENT", self.provider)
        ).generate_text(message, additional_instructions, uri=uri, context=context)
