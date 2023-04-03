import os
import uuid
from base64 import b64decode

import openai

from ..logger import log


class OpenAI:
    def __init__(self):
        openai.api_key = os.environ.get("OPENAI_KEY")

    def generate_image(self, prompt, size="512x512", name="img-", path="static/images/", n=1, overwrite=False):

        response = openai.Image.create(
            prompt=prompt, n=n, size=size, response_format="b64_json"
        )
        images = []
        for index, image_dict in enumerate(response["data"]):
            image_data = b64decode(image_dict["b64_json"])
            img_path = f"{path}{name}{uuid.uuid4()}.png"
            with open(img_path, mode="wb") as png:
                png.write(image_data)
                images.append(img_path)
        return images
