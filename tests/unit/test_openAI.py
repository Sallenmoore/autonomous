import json

import pytest

from autonomous import log
from autonomous.apis import OpenAI


# @pytest.mark.skip(reason="OpenAI API is not free")
class TestOpenAI:
    def test_init(self):
        oai = OpenAI()
        assert oai

    def test_generate_image(self):
        oai = OpenAI()
        prompt = (
            "A beautiful pasture that seems directly out of a William Wordsworth poem."
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

    def test_summarize_text(self):
        primer_text = "As a nihilistic AI, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = OpenAI().summarize_text(prompt, primer_text)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)
