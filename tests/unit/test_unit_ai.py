import io
import json

import pytest

from autonomous import log
from autonomous.ai.oaiagent import OAIAgent

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


# @pytest.mark.skip(reason="This test is not yet implemented")
class TestOAIAgent:
    @pytest.mark.skip(reason="working")
    def test_generate_image(self):
        oai = OAIAgent(name="TestAgent")
        prompt = (
            "A beautiful pasture that seems directly out of a William Wordsworth poem."
        )
        img = oai.generate_image(prompt)
        assert isinstance(img, bytes)
        with open("tests/assets/testimg.png", "wb") as fptr:
            fptr.write(img)

    @pytest.mark.skip(reason="working")
    def test_summarize_text(self):
        primer_text = "As a nihilistic AI, you will try to emphasize the absurdities of the text in your summary."
        prompt = " It was 7 minutes after midnight. The dog was lying on the grass in the middle of the lawn in front of Mrs Shears’ house. Its eyes were closed. It looked as if it was running on its side, the way dogs run when they think they are chasing a cat in a dream. But the dog was not running or asleep. The dog was dead. There was a garden fork sticking out of the dog. The points of the fork must have gone all the way through the dog and into the ground because the fork had not fallen over. I decided that the dog was probably killed with the fork because I could not see any other wounds in the dog and I do not think you would stick a garden fork into a dog after it had died for some other reason, like cancer for example, or a road accident. But I could not be certain about this."

        result = OAIAgent(instructions=primer_text).summarize_text(prompt)
        # log(result)
        assert result
        open("tests/assets/summary.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_text(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OAIAgent(name="comedian", instructions=primer_text)
        result = oai.generate(prompt)
        assert result
        open("tests/assets/testjoke.txt", "w").write(result)

    @pytest.mark.skip(reason="working")
    def test_generate_json(self):
        primer_text = "You are a writer's assistant for a comedian. The comedian is helpful, creative, clever, and very funny."
        prompt = "Write a joke about programming."
        oai = OAIAgent(name="comedian", instructions=primer_text)
        result = oai.generate(prompt, function=funcobj)
        joke = json.loads(result)
        assert joke["humor_num"]
        assert joke["text"]
        open("tests/assets/testjoke.json", "w").write(result)

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

        primer_text = "You are an AI assistant helping create characters for D&D game master. Use the knowledge of existing characters to make the new character consistent and have some connection to with the existing characters in the world."
        prompt = "Generate a new NPC with all required details."
        oai = OAIAgent(instructions=primer_text)
        oai.save()
        file_id = oai.attach_file(char_str)
        result = oai.generate(prompt, function=char_funcobj)
        assert result.get("name")
        json.dump(result, open("tests/assets/character.json", "w"))
        oai_2 = OAIAgent.get(oai.pk)
        file_list = oai_2.clear_files(file_id)
        for file in file_list.data:
            assert file.id != file_id
        # file_list = oai_2.clear_files()
        # assert file_list.data == []
