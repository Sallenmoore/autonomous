import os
import uuid
from base64 import b64decode
import random

import openai

from ..logger import log


class OpenAI:
    def __init__(self):
        openai.api_key = os.environ.get("OPENAI_KEY")

    def generate_image(
        self,
        prompt,
        size="512x512",
        n=1,
    ):
        images = []

        try:
            response = openai.Image.create(
                prompt=prompt, n=n, size=size, response_format="b64_json"
            )
        except Exception as e:
            log(f"{e}\n\n==== Error: fall back to lesser model ====")
            images = ["https://picsum.photos/400/?blur"]
        else:
            for index, image_dict in enumerate(response["data"]):
                image_data = b64decode(image_dict["b64_json"])
                images.append(image_data)
        return images

    def generate_text(self, text, primer_text="", functions=None):
        json_data = {}
        json_data["messages"] = [
            {
                "role": "system",
                "content": primer_text,
            },
            {
                "role": "user",
                "content": text,
            },
        ]

        if isinstance(functions, (list, tuple)):
            json_data.update({"functions": functions})
        elif functions is not None:
            json_data.update({"function_call": {"name": functions["name"]}})
            json_data.update({"functions": [functions]})
        # breakpoint()
        try:
            response = openai.ChatCompletion.create(model="gpt-4-0613", **json_data)
        except Exception as e:
            log(f"{type(e)}:{e}\n\n==== Error: fall back to lesser model ====")
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo-0613", **json_data
            )
        # breakpoint()
        try:
            result = response["choices"][0]["message"]["function_call"]["arguments"]
        except KeyError:
            result = response["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"{type(e)}:{e}\n\n Unable to generate content ====")
            return e

        return result
