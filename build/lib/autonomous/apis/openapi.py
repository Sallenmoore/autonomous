import os
from base64 import b64decode

import openai

from .logger import log


class OpenAI:
    def __init__(self):
        openai.api_key = os.environ.get("OPENAI_KEY")

    def generate_image(self, prompt, size="512x512", path="static/images/temp", n=1):

        try:
            response = openai.Image.create(
                prompt=prompt, n=n, size=size, response_format="b64_json"
            )
        except Exception as e:
            log(f"Image Generation Failed: {e}")
        else:
            for index, image_dict in enumerate(response["data"]):
                image_data = b64decode(image_dict["b64_json"])
                img_path = f"{path}-{index+1}.png"
                if not os.path.isfile(img_path):
                    with open(img_path, mode="wb") as png:
                        png.write(image_data)
