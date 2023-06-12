import os
import shutil
import json
import random
import sys
from slugify import slugify

from datetime import datetime
from autonomous.logger import log
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from .. import OpenAI
from .dndobject import Monster, Item, Spell
from .dndplayer import Player
from .dndnpc import NPC
from .dndshop import Shop


class OpenDnD:
    """
    _summary_

    Returns:
        _type_: _description_
    """

    LOOT_MULTIPLIER = 3

    @classmethod
    def updatedb(cls):
        Monster.update_db()
        Spell.update_db()
        Item.update_db()

    @classmethod
    def _query(cls, api, **kwargs):
        # log(api, kwargs)
        if "pk" in kwargs:
            results = [api.get(kwargs["pk"])]
        elif kwargs:
            kwargs["slug"] = slugify(kwargs.get("name", ""))
            results = api.search(**kwargs)
        else:
            results = api.all()
        return results

    @classmethod
    def monsters(cls, **kwargs):
        return cls._query(Monster, **kwargs)

    @classmethod
    def items(cls, **kwargs):
        return cls._query(Item, **kwargs)

    @classmethod
    def spells(cls, **kwargs):
        return cls._query(Spell, **kwargs)

    @classmethod
    def players(cls, **kwargs):
        # log(kwargs)
        return cls._query(Player, **kwargs)

    @classmethod
    def shops(cls, **kwargs):
        return cls._query(Shop, **kwargs)

    @classmethod
    def npcs(cls, **kwargs):
        return cls._query(NPC, **kwargs)

    @classmethod
    def generatenpc(cls, name=None, summary=None, generate_image=False):
        age = random.randint(15, 100)
        personality = [
            "shy",
            "outgoing",
            "friendly",
            "mean",
            "snooty",
            "aggressive",
            "sneaky",
            "greedy",
            "kind",
            "generous",
            "smart",
            "dumb",
            "loyal",
            "dishonest",
            "honest",
            "lazy",
            "hardworking",
            "stubborn",
            "flexible",
            "proud",
            "humble",
            "confident",
            "insecure",
            "courageous",
            "cowardly",
            "optimistic",
            "pessimistic",
            "silly",
            "serious",
            "sensitive",
            "insensitive",
            "creative",
            "imaginative",
            "practical",
            "logical",
            "intuitive",
            "intelligent",
            "wise",
            "foolish",
            "curious",
            "nosy",
            "adventurous",
            "cautious",
            "careful",
            "reckless",
            "careless",
            "patient",
            "impatient",
            "tolerant",
            "intolerant",
            "forgiving",
            "unforgiving",
            "honest",
            "unfriendly",
            "outgoing",
            "shy",
            "sneaky",
            "honest",
            "dishonest",
            "disloyal",
            "unfriendly",
        ]

        primer = """
        You are a D&D 5e NPC generator that creates random NPC's with a full name, backstory, class, occupation, and character stats. Respond to prompts only with the following json schema:
        {
            "name": string,
            "age": int,
            "gender": string,
            "race": string,
            "personality": [string],
            "backstory": string,
            "class_name": string,
            "occupation": string,
            "inventory": [string],
            "stats": {
                "str": int,
                "dex": int,
                "con": int,
                "int": int,
                "wis": int,
                "cha": int
            }
        }
        """
        traits = ", ".join(random.sample(personality, 3))
        prompt = f"Generate an NPC aged {age} years with the following personality traits: {traits}"
        log(prompt)
        response = OpenAI().generate_text(prompt, primer)
        npc_json = response[response.find("{") : response.rfind("}") + 1]
        npc_data = json.loads(npc_json)
        npc_data["desc"] = npc_data["backstory"]
        npc = NPC(**npc_data)
        return npc

    @classmethod
    def generateencounter(cls, num_players=5, level=1):
        difficulty_list = [
            "trivial",
            "easy",
            "medium",
            "hard",
            "deadly",
        ]
        loot = [
            "gold",
            "gems",
            "magic items",
            "misc",
            "weapons",
            "armor",
        ]

        primer = """
        You are a D&D 5e Encounter generator that creates level appropriate random encounters and specific loot rewards. Respond to prompts only with the following json schema:
        {
            "difficulty": string,
            "enemies": [string],
            "loot": [string],
        }
        """
        difficulty = random.choice(list(enumerate(difficulty_list)))
        loot_type = random.choices(
            loot,
            weights=[10, 5, 3, 30, 10, 10],
            k=difficulty[0] * OpenDnD.LOOT_MULTIPLIER,
        )
        prompt = f"Generate an appropriate encounter for a party of {num_players} level {level} pcs that is {difficulty[1]} and rewards the following type of loot items: {loot_type}"
        encounter = OpenAI().generate_text(prompt, primer)
        encounter = encounter[encounter.find("{") : encounter.rfind("}") + 1]
        encounter = json.loads(encounter)
        return encounter

    @classmethod
    def generateshop(cls):
        primer = """
        You are a D&D 5e Shop generator that creates random shops. Respond to prompts only with the following json schema:
        {
            "name": string,
            "shoptype": string,
            "description": string,
            "inventory": [
                {
                    "name": string,
                    "description": string,
                    "cost": string,
                }
            }
        }
        """
        prompt = "Generate a random shop"
        shop = OpenAI().generate_text(prompt, primer)
        shop = shop[shop.find("{") : shop.rfind("}") + 1]
        shop = json.loads(shop)
        shopowner = cls.generatenpc(
            summary=f"Owner of {shop['name']}, a {shop['shoptype']} shop."
        )
        shopowner.save()
        shop["owner"] = shopowner
        shop["desc"] = shop["description"]
        del shop["description"]
        shop_obj = Shop(**shop)
        shop_obj.save()
        return shop_obj
