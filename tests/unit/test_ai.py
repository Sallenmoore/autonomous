import json

import pytest
from autonomous import log
from autonomous.ai import AutoTeam
from autonomous.ai.agents.mockai import MockAIAgent

# from autonomous.ai.agents.local import LocalAIAgent
from autonomous.ai.agents.openai import OpenAIAgent

# from autonomous.ai.agents.autogen import AutoGenAgent


funcobj = {
    "name": "evaluate_joke",
    "description": "Evaluate a joke for humor rating",
    "parameters": {
        "type": "object",
        "properties": {
            "humor_num": {
                "type": "integer",
                "description": "How humorous the joke is on a scale of 1-100",
            },
            "text": {
                "type": "string",
                "description": "The text of the joke",
            },
            "influences": {
                "type": "array",
                "description": "A list of comedians who influenced the joke",
                "items": {"type": "string"},
            },
            "word_count_by_sentence": {
                "type": "array",
                "description": "The number of words in each sentence e of the joke",
                "items": {"type": "integer"},
            },
        },
    },
}
funcobj["parameters"]["required"] = list(funcobj["parameters"]["properties"].keys())


class TestAutoTeam:
    def test_init(self):
        oai = AutoTeam()
        assert oai


@pytest.mark.skip(reason="This test is not yet implemented")
class TestOpenAIAgent:
    def test_generate_image(self):
        oai = AutoTeam(OpenAIAgent)
        prompt = (
            "A beautiful pasture that seems directly out of a William Wordsworth poem."
        )
        img = oai.generate_image(prompt)
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)

    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        joke = AutoTeam(OpenAIAgent).generate_text(prompt, primer_text)
        assert joke
        open("tests/assets/testjoke.txt", "w").write(joke)

    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        # log(funcobj)
        result = AutoTeam(OpenAIAgent).generate_json(
            prompt, funcobj, primer_text=primer_text
        )
        # log(result)

        joke = json.loads(result)
        assert joke["topic"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(result)

    def test_summarize_text(self):
        primer_text = "As a nihilistic AI, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = AutoTeam(OpenAIAgent).summarize_text(prompt, primer_text)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)


class TestMockAI:
    def test_init(self):
        oai = AutoTeam(MockAIAgent)
        assert oai

    def test_generate_image(self):
        oai = AutoTeam(MockAIAgent)
        prompt = (
            "A beautiful pasture that seems directly out of a William Wordsworth poem."
        )
        img = oai.generate_image(prompt)
        log(type(img))
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)

    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        joke = AutoTeam(MockAIAgent).generate_text(prompt, primer_text)
        assert joke
        open("tests/assets/testjoke.txt", "w").write(joke)

    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        # log(funcobj)
        result = AutoTeam(MockAIAgent).generate_json(
            prompt, funcobj, primer_text=primer_text
        )
        # log(result)

        joke = json.loads(result)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(result)

    def test_summarize_text(self):
        primer_text = "As a nihilistic AI, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = AutoTeam(MockAIAgent).summarize_text(prompt, primer_text)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)
