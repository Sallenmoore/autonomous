import json
import os

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai._json_utils import _schema_validate
from autonomous.ai.exceptions import GenerateJSONParseError
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

        # Per-provider dispatch. Gemini's existing function= parameter
        # already IS a JSON-schema carrier (function.parameters), so we
        # synthesize a function dict from json_schema. Other providers
        # accept json_schema= directly.
        if provider == "gemini":
            function = None
            if json_schema is not None:
                function = {
                    "name": schema_name,
                    "description": "Structured response shape.",
                    "parameters": json_schema,
                }
            result = client.generate_json(
                message,
                function=function,
                additional_instructions=system_prompt,
                uri=uri,
                context=context,
                **kwargs,
            )
        else:
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
            except json.JSONDecodeError as exc:
                # Per MIGRATIONS' typed-exception contract, JSON parse
                # failures surface as GenerateJSONParseError (not bare
                # ValueError) so callers can catch the typed hierarchy.
                # Raw body is preserved on .raw for diagnostics.
                raise GenerateJSONParseError(
                    f"Invalid JSON response from AI model.",
                    raw=result,
                ) from exc
        elif not isinstance(result, dict):
            raise GenerateJSONParseError(
                f"Invalid JSON response from AI model: "
                f"expected dict or JSON string, got {type(result).__name__}.",
                raw=str(result),
            )

        # Defense in depth: validate every provider's output. Catches
        # provider bugs even when the provider claims schema compliance
        # (gemini function-calling, OpenAI strict mode). No-op when
        # json_schema is None.
        _schema_validate(result, json_schema, raw=json.dumps(result)[:500])

        self.add_to_job_meta("Last JSON", result)
        return result
