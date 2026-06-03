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

    def generate(
        self,
        message,
        system_prompt="",
        uri="",
        context="",
        temperature=None,
        json_schema=None,
        schema_name="response",
    ):
        provider = os.environ.get("JSON_AI_AGENT", self.provider)
        client = self.get_client(provider)

        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature

        # Per-provider dispatch. Gemini's branch lands in Task 10 — for now,
        # all providers receive json_schema= as a passthrough kwarg.
        result = client.generate_json(
            message,
            system_prompt=system_prompt,
            uri=uri,
            context=context,
            json_schema=json_schema,
            schema_name=schema_name,
            **kwargs,
        )

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        elif not isinstance(result, dict):
            raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")

        # Centralized client-side validation lands in Task 11.

        self.add_to_job_meta("Last JSON", result)
        return result
