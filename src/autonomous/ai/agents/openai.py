import os
from base64 import b64decode

from openai import OpenAI

from autonomous import log


class OpenAIAgent:
    client = None

    def __init__(self, **kwargs):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_KEY"))

    def generate(self, prompt, primer_text="", **kwargs):
        return self.generate_text(self, prompt, primer_text)

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

    def generate_json(self, text, functions, primer_text=""):
        json_data = {
            # "response_format":{ "type": "json_object" },
            "messages": [
                {
                    "role": "system",
                    "content": f"{primer_text}. Your output must be a JSON object.",
                },
                {
                    "role": "user",
                    "content": text,
                },
            ]
        }

        if isinstance(functions, (list, tuple)):
            json_data.update({"functions": functions})
        elif functions is not None:
            json_data.update({"function_call": {"name": functions["name"]}})
            json_data.update({"functions": [functions]})

        # try:
        response = self.client.chat.completions.create(model="gpt-4", **json_data)
        # except Exception as e:
        #     log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
        #     response = self.client.chat.completions.create(
        #         model="gpt-3.5-turbo", **json_data
        #     )
        # breakpoint()
        try:
            result = response.choices[0].message.function_call.arguments
        except Exception as e:
            log(f"==== Unable to generate content ====\n\n{type(e)}:{e}")
            return None

        return result

    def generate_text(self, text, primer_text=""):
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
