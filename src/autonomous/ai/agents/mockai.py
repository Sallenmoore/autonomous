import base64
import json
import random
import urllib

import requests


class MockAIAgent:
    def generate_image(self, prompt, **kwargs):
        prompt = urllib.parse.quote_plus(prompt)
        response = requests.get(f"https://placehold.co/600x400/png?text={prompt}")
        return response.content

    def _generate_json(self, attributes):
        data = {"string": "mock", "integer": 1, "array": [], "object": {}}
        obj = {}
        for k, v in attributes.items():
            if v["type"] == "string":
                obj[k] = data["string"]
            elif v["type"] == "integer":
                obj[k] = data["integer"]
            elif v["type"] == "array":
                obj[k] = data["array"]
                for i in range(random.randrange(1, 10)):
                    obj[k].append(v["type"])
            elif v["type"] == "object":
                obj[k] = data["object"]
                for name, val in v["properties"].items():
                    obj[k][name] = val["type"]
            else:
                raise Exception(f"Unknown type: {v['type']}")
        return obj

    def generate_json(
        self,
        text,
        functions,
        primer_text="",
    ):
        obj = self._generate_json(functions["parameters"]["properties"])
        return json.dumps(obj)

    def generate_text(self, text, primer_text=""):
        return f"**PRIMER**: {primer_text}, **TEXT**: {text}"

    def summarize_text(self, text, primer_text=""):
        return f"**SUMMARY**: {text[:text.find('.') + 1]}"
