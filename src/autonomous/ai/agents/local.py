import json
import os
import requests

from dotenv import load_dotenv

load_dotenv()


class LocalAIAgent:
    endpoint = "http://localhost:8000"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer ?",
    }

    client = None

    def __init__(cls, **kwargs):
        if not cls.client:
            cls.client = None

    @classmethod
    def make_request(cls, data):
        # log(query)
        # log(**obj_vars)

        response = requests.post(
            cls.endpoint,
            headers=cls.headers,
            json=data,
        )
        if response.status_code != 200:
            raise Exception(response.text)

        return response

    def generate_image(self, prompt, **kwargs):
        return self.make_request(
            {
                "prompt": prompt,
                **kwargs,
            }
        )

    def generate_json(
        self,
        text,
        functions,
        primer_text="",
    ):
        return self.make_request(
            {
                "text": text,
                "functions": functions,
                "primer_text": primer_text,
            }
        )

    def generate_text(self, text, primer_text=""):
        return self.make_request(
            {
                "text": text,
                "primer_text": primer_text,
            }
        )

    def summarize_text(self, text, primer_text=""):
        return self.make_request(
            {
                "text": text,
                "primer_text": primer_text,
            }
        )
