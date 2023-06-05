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
        name="img-",
        path=None,
        n=1,
    ):
        try:
            response = openai.Image.create(
                prompt=prompt, n=n, size=size, response_format="b64_json"
            )
        except Exception as e:
            log(e)
            return ""
        else:
            images = []
            for index, image_dict in enumerate(response["data"]):
                image_data = b64decode(image_dict["b64_json"])
                if path:
                    img_path = f"{path}/{name}.png"
                    with open(img_path, mode="wb") as png:
                        png.write(image_data)
                        images.append(img_path)
                else:
                    images.append(image_data)
        return images

    def generate_text(self, text, prime_text):
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": prime_text,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
        )
        return response["choices"][0]["message"]["content"]
