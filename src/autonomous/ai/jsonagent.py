import json
import os

from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


class JSONAgent(BaseAgent):
    name = StringAttr(default="jsonagent")

    # Force this agent to use Gemini
    provider = StringAttr(default="gemini")

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating JSON formatted data."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating JSON formatted data."
    )

    def generate(self, message, system_prompt="", uri="", context=""):
        result = self.get_client(
            os.environ.get("JSON_AI_AGENT", self.provider)
        ).generate_json(message, system_prompt=system_prompt, uri=uri, context=context)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        elif not isinstance(result, dict):
            raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        return result
