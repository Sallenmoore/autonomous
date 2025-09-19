import json
import os

import pytest

from autonomous import log
from autonomous.ai.audioagent import AudioAgent
from autonomous.ai.imageagent import ImageAgent
from autonomous.ai.jsonagent import JSONAgent
from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.openai import OpenAIModel
from autonomous.ai.textagent import TextAgent

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


char_funcobj = {
    "name": "generate_npc",
    "description": "completes NPC data object",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A unique first, middle, and last name",
            },
            "age": {
                "type": "integer",
                "description": "The character's age",
            },
            "gender": {
                "type": "string",
                "description": "The character's preferred gender",
            },
            "race": {
                "type": "string",
                "description": "The character's race",
            },
            "traits": {
                "type": "array",
                "description": "The character's personality traits",
                "items": {"type": "string"},
            },
            "desc": {
                "type": "string",
                "description": "A physical description that will be used to generate an image of the character",
            },
            "backstory": {
                "type": "string",
                "description": "The character's backstory that includes an unusual secret the character must protect",
            },
            "goal": {
                "type": "string",
                "description": "The character's goal",
            },
            "occupation": {
                "type": "string",
                "description": "The character's daily occupation",
            },
            "strength": {
                "type": "integer",
                "description": "The amount of Strength the character has from 1-20",
            },
            "dexterity": {
                "type": "integer",
                "description": "The amount of Dexterity the character has from 1-20",
            },
            "constitution": {
                "type": "integer",
                "description": "The amount of Constitution the character has from 1-20",
            },
            "intelligence": {
                "type": "integer",
                "description": "The amount of Intelligence the character has from 1-20",
            },
            "wisdom": {
                "type": "integer",
                "description": "The amount of Wisdom the character has from 1-20",
            },
            "charisma": {
                "type": "integer",
                "description": "The amount of Charisma the character has from 1-20",
            },
            "notes": {
                "type": "array",
                "description": "3 short descriptions of potential side quests involving the character",
                "items": {"type": "string"},
            },
        },
    },
}
char_funcobj["parameters"]["required"] = list(
    funcobj["parameters"]["properties"].keys()
)


class TestGeminiModel:
    # def summarize_text(self, text, primer=""):
    @pytest.mark.skip(reason="These tests are working")
    def test_summarize_text(self):
        primer_text = "As a nihilistic AI that summarizes text, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = GeminiAIModel(instructions=primer_text).summarize_text(
            prompt, primer=primer_text
        )
        log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)

    # def generate_text(self, message, additional_instructions=""):
    @pytest.mark.skip(reason="These tests are working")
    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        result = GeminiAIModel(name="comedian", instructions=primer_text).generate_text(
            prompt
        )
        assert result
        open("tests/assets/testjoke.txt", "w").write(result)

    # def generate_json(self, message, function, additional_instructions=""):
    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = GeminiAIModel(name="comedian", instructions=primer_text)
        joke = oai.generate_json(prompt, function=funcobj)
        if isinstance(joke, str):
            joke = json.loads(joke)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(f"{joke}")

    # def generate_audio_text(self, audio_file, **kwargs):
    def test_generate_audio_text(self):
        with open("tests/assets/testaudio.mp3", "rb") as f:
            audio_bytes = f.read()
            result = GeminiAIModel().generate_audio_text(audio_bytes)
        # log(result)
        assert result
        open("tests/assets/audio_text.txt", "w").write(result)

    # def generate_audio_text(self, audio_file, **kwargs):
    def test_generate_audio(self):
        prompt = "April is the cruellest month, breeding Lilacs out of the dead land, mixing Memory and desire, stirring Dull roots with spring rain"

        result = GeminiAIModel().generate_audio(prompt)
        # log(result)
        assert result
        open("tests/assets/newaudio.mp3", "w").write(result)

    # def generate_image(self, prompt, **kwargs):
    def test_generate_image(self):
        oai = GeminiAIModel(name="TestAgent")
        prompt = (
            "An existential scene that seems directly out of a Robert Browning poem."
        )
        img = oai.generate_image(prompt)
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)


@pytest.mark.skip(reason="These tests are working")
class TestLocalModel:
    @pytest.mark.skip(reason="working")
    def test_summarize_text(self):
        primer_text = "As a nihilistic AI that summarizes text, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = OpenAIModel(instructions=primer_text).summarize_text(prompt)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OpenAIModel(name="comedian", instructions=primer_text)
        result = oai.generate_text(prompt)
        assert result
        open("tests/assets/testjoke.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OpenAIModel(name="comedian", instructions=primer_text)
        joke = oai.generate_json(prompt, function=funcobj)
        if isinstance(joke, str):
            joke = json.loads(joke)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(f"{joke}")


@pytest.mark.skip(reason="These tests are working")
class TestOAIModel:
    def test_generate_audio(self):
        oai = OpenAIModel(name="TestAgent")
        prompt = (
            "An existential scene that seems directly out of a Robert Browning poem."
        )
        response = oai.generate_audio(prompt, voice="echo")
        assert isinstance(response.read(), bytes)
        with open("tests/assets/testaudio.mp3", "wb") as fptr:
            fptr.write(response.read())

    @pytest.mark.skip(reason="working")
    def test_generate_image(self):
        oai = OpenAIModel(name="TestAgent")
        prompt = (
            "An existential scene that seems directly out of a Robert Browning poem."
        )
        img = oai.generate_image(prompt)
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)

    @pytest.mark.skip(reason="working")
    def test_summarize_text(self):
        primer_text = "As a nihilistic AI that summarizes text, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = OpenAIModel(instructions=primer_text).summarize_text(prompt)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OpenAIModel(name="comedian", instructions=primer_text)
        result = oai.generate_text(prompt)
        assert result
        open("tests/assets/testjoke.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OpenAIModel(name="comedian", instructions=primer_text)
        joke = oai.generate_json(prompt, function=funcobj)
        if isinstance(joke, str):
            joke = json.loads(joke)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(f"{joke}")

    @pytest.mark.skip(reason="working")
    def test_file_add(self):
        result = json.load(open("tests/assets/data.json"))
        characters = result["character"]
        for character in characters:
            character.pop("_world")
            character.pop("_parent_obj")
            character.pop("bs_summary")
            character.pop("asset_id")
            character.pop("battlemap")
            character.pop("wiki_id")
            character.pop("_journal")
            character.pop("_relations")
            character.pop("notes")
            character.pop("_items")
            character.pop("chats")
            character.pop("pk")
            character.pop("last_updated")
            character.pop("_automodel")
        char_str = json.dumps(characters).encode("utf-8")
        assert char_str

        primer_text = "You are an AI assistant helping create characters for D&D game master. Use the knowledge of existing characters to make the new character consistent with and have some connection to the existing characters in the world."
        prompt = "Generate a new NPC with all required details."
        oai = OpenAIModel(instructions=primer_text)
        oai.save()
        file_id = oai.attach_file(char_str)
        result = oai.generate_json(prompt, function=char_funcobj)
        assert result.get("name")
        json.dump(result, open("tests/assets/character.json", "w"))
        oai_2 = OpenAIModel.get(oai.pk)
        file_list = oai_2.clear_files(file_id)
        for file in file_list.data:
            assert file.id != file_id

    @pytest.mark.skip(reason="working")
    def test_clean_resources(self):
        ai = OpenAIModel()
        ai.save()
        ai.clear_files()
        ai.clear_agents()


@pytest.mark.skip(reason="These tests are working")
class TestImageAgent:
    # @pytest.mark.skip(reason="working")
    def test_generate_image(self):
        ai = ImageAgent(name="TestImageAgent")
        prompt = (
            "A beautiful pasture that seems directly out of a William Wordsworth poem."
        )
        img = ai.generate(prompt)
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)


@pytest.mark.skip(reason="These tests are working")
class TestAudioAgent:
    # @pytest.mark.skip(reason="working")
    def test_generate_audio(self):
        ai = AudioAgent(name="TestAudioAgent")
        prompt = "The tintinabulation that so musically wells from the bells, bells, bells, bells, Bells, bells, bells — From the jingling and the tinkling of the bells."
        ai.generate(prompt, "tests/assets/testaudio.mp3")
        assert os.path.exists("tests/assets/testaudio.mp3")


@pytest.mark.skip(reason="These tests are working")
class TestTextAgent:
    # @pytest.mark.skip(reason="working")
    def test_summarize_text(self):
        primer_text = "As a nihilistic AI, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."
        ai = TextAgent(name="TestSummaryAgent", instructions=primer_text)
        result = ai.summarize_text(prompt)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)

    # @pytest.mark.skip(reason="working")
    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        ai = TextAgent(name="TestTextAgent", instructions=primer_text)
        result = ai.generate(prompt, additional_instructions="Make it a about python.")
        assert result
        open("tests/assets/testjoke.txt", "w").write(result)


@pytest.mark.skip(reason="These tests are working")
class TestJSONAgent:
    @pytest.mark.skip(reason="working")
    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        ai = JSONAgent(name="comedian", instructions=primer_text)
        joke = ai.generate(prompt, function=funcobj)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(f"{joke}")

    @pytest.mark.skip(reason="working")
    def test_file_add(self):
        result = json.load(open("tests/assets/data.json"))
        characters = result["character"]
        for character in characters:
            character.pop("_world")
            character.pop("_parent_obj")
            character.pop("bs_summary")
            character.pop("asset_id")
            character.pop("battlemap")
            character.pop("wiki_id")
            character.pop("_journal")
            character.pop("_relations")
            character.pop("notes")
            character.pop("_items")
            character.pop("chats")
            character.pop("pk")
            character.pop("last_updated")
            character.pop("_automodel")
        char_str = json.dumps(characters).encode("utf-8")
        assert char_str

        primer_text = "You are an AI assistant helping create characters for D&D game master. Use the uploaded file to ensure consistency with and create connections backstory to other characters in the world."
        prompt = "Generate a new NPC using the uploaded file of existing characters to create a new and unique character that are consistent with and have a connection to at least 2 existing characters in the world."
        ai = JSONAgent(name="character_creator", instructions=primer_text)
        ai.save()
        ai.get_client().attach_file(char_str)
        result = ai.generate(prompt, function=char_funcobj)
        assert result.get("name")
        json.dump(result, open("tests/assets/character.json", "w"))


@pytest.mark.skip(reason="working")
def test_clean():
    ai = OpenAIModel()
    ai.save()
    ai.clear_files()
    ai.clear_agents()
