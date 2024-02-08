import json
import os
from base64 import b64decode

from openai import OpenAI

from autonomous import log


class OpenAIAgent:
    client = None

    _instructions_addition = """
        IMPORTANT: always use the function 'response' tool to respond to the user with the requested JSON schema. Never add any other text to the response.
        """

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

    def generate_audio(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.images.generate(
                model="dall-e-3", prompt=prompt, response_format="b64_json", **kwargs
            )
            image_dict = response.data[0]
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}")
        else:
            image = b64decode(image_dict.b64_json)
        return image

    def generate_image(self, prompt, **kwargs):
        image = None
        try:
            response = self.client.images.generate(
                model="dall-e-3", prompt=prompt, response_format="b64_json", **kwargs
            )
            image_dict = response.data[0]
        except Exception as e:
            log(f"==== Error: Unable to create image ====\n\n{e}")
        else:
            image = b64decode(image_dict.b64_json)
        return image

    def generate_json(
        self, text, function, name=None, primer_text="", file_data=None, context=[]
    ):
        json_data = {
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": f"{primer_text}. {self._instructions_addition}",
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            "tools": [{"type": "function", "function": function}],
            "tool_choice": {"type": "function", "function": {"name": function["name"]}},
        }

        try:
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview", **json_data
            )
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(model="gpt-4", **json_data)
        # breakpoint()
        try:
            results = response.message.tool_calls[0].function.arguments
            results = results[results.find("{") : results.rfind("}") + 1]
            log(results)
            json_result = json.loads(results)
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return json_result

    def generate_text(
        self, text, name="text_agent", primer_text="", file_data=None, context=[]
    ):
        json_data = {
            "messages": [
                {
                    "role": "system",
                    "content": primer_text,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ]
        }

        try:
            response = self.client.chat.completions.create(model="gpt-4", **json_data)
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo", **json_data
            )
        # breakpoint()
        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return result

    def summarize_text(self, text, primer=""):
        message = [
            {
                "role": "system",
                "content": f"You are a highly skilled AI trained in language comprehension and summarization.{primer}",
            },
            {"role": "user", "content": text},
        ]
        try:
            response = self.client.chat.completions.create(
                model="gpt-4", temperature=0, messages=message
            )
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = self.client.chat.completions.create(
                model="gpt-4", temperature=1, messages=message
            )
        # breakpoint()

        try:
            result = response.choices[0].message.content
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return e

        return result
