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
        path="static/images",
        n=1,
        overwrite=False,
    ):
        os.makedirs(path, exist_ok=True)
        try:
            response = openai.Image.create(
                prompt=prompt, n=n, size=size, response_format="b64_json"
            )
            images = []
            for index, image_dict in enumerate(response["data"]):
                image_data = b64decode(image_dict["b64_json"])
                img_path = f"{path}/{name}.png"
                with open(img_path, mode="wb") as png:
                    png.write(image_data)
                    images.append(img_path)
        except Exception as e:
            log(e)
            images = ["https://dummyimage.com/400x400/6a4891/5c5f8c.png"]
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
