import pytest
import json
from autonomous import log
from autonomous.apis import OpenAI


class TestOpenAI:
    def test_init(self):
        oai = OpenAI()
        assert oai

    def test_generate_image(self):
        oai = OpenAI()
        prompt = (
            "The random image that illustrates AI capabilities with image generation"
        )
        imgs = oai.generate_image(prompt, size="256x256", n=1)
        for img in imgs:
            assert isinstance(img, bytes)
            with open("tests/assets/testimg.png", "wb") as fptr:
                fptr.write(img)

    def test_generate_text(self):
        primer_text = "The following is a conversation with a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        funcobj = {
            "name": "evaluate_joke",
            "description": "Evaluate a joke for humor rating",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic of the joke",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text of the joke",
                    },
                },
            },
        }
        funcobj["parameters"]["required"] = list(
            funcobj["parameters"]["properties"].keys()
        )
        # log(funcobj)
        result = OpenAI().generate_text(prompt, primer_text, functions=funcobj)
        # log(result)

        joke = json.loads(result)
        assert joke["topic"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(result)
