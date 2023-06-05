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
from .dndobject import DnDMonster, DnDItem, DnDSpell, DnDPlayer, DnDNPC, DnDShop


class OpenDnD:
    """
    _summary_

    Returns:
        _type_: _description_
    """

    storage = CloudinaryStorage()

    imgpath = f"{os.path.dirname(sys.modules[__name__].__file__)}/imgs"

    @classmethod
    def has_image(cls, fname):
        if random.randrange(50):
            items = os.listdir(cls.imgpath)
            random.shuffle(items)
            for i in items:
                testname = i.split(".")[0] if "." in i else i
                testname = testname.split("--")[0] if "--" in testname else testname
                if fname.lower() == testname.lower():
                    return f"{i}"

    @classmethod
    def get_image(cls, name):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        name = slugify(name)
        img_file = cls.has_image(name)
        description = random.choice(["A portrait", "in action", "in a scene"])
        style = random.choice(["pixar style 3d", "sketch and watercolor"])
        if not img_file:
            prompt = f"A full color {style} portrait of a {name} from Dungeons and Dragons 5e - {description}"
            try:
                resp = OpenAI().generate_image(
                    prompt,
                    name=f"{name}--{datetime.now().toordinal()}",
                    path=f"{cls.imgpath}",
                    n=1,
                )
                img_file = resp[0]
            except Exception as e:
                log(e)
        # log(img_file)
        static_directory = "static/images/dnd"
        if not os.path.exists(static_directory):
            os.makedirs(static_directory)
        if not os.path.exists(f"{static_directory}/{os.path.basename(img_file)}"):
            shutil.copy(img_file, f"{static_directory}/{os.path.basename(img_file)}")

        return f"/{static_directory}/{os.path.basename(img_file)}"

    @classmethod
    def _process_results(cls, results):
        new_results = []
        for i, r in enumerate(results):
            if not results[i].image:
                results[i].image = cls.get_image(results[i].name)
            new_results.append(results[i])
        return new_results

    @classmethod
    def _process_search_terms(cls, **terms):
        if terms.get("name"):
            terms["slug"] = slugify(terms["name"])
        return terms

    @classmethod
    def monsters(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDMonster.get(kwargs["pk"])]
            return cls._process_results(results)
        elif kwargs:
            return DnDMonster.search(**kwargs)
        return cls._process_results(DnDMonster.all())

    @classmethod
    def items(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDItem.get(kwargs["pk"])]
            return cls._process_results(results)
        elif kwargs:
            return DnDItem.search(**kwargs)
        return cls._process_results(DnDItem.all())

    @classmethod
    def spells(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDSpell.get(kwargs["pk"])]
            return cls._process_results(results)
        elif kwargs:
            return DnDSpell.search(**kwargs)
        return cls._process_results(DnDSpell.all())

    @classmethod
    def players(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDPlayer.get(kwargs["pk"])]
            return results
        elif kwargs:
            return DnDPlayer.search(**kwargs)
        return DnDPlayer.all()

    @classmethod
    def shops(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDShop.get(kwargs["pk"])]
            return results
        elif kwargs:
            return DnDShop.search(**kwargs)
        return DnDShop.all()

    @classmethod
    def npcs(cls, **kwargs):
        if "pk" in kwargs:
            results = [DnDNPC.get(kwargs["pk"])]
            return results
        elif kwargs:
            return DnDNPC.search(**kwargs)
        return DnDNPC.all()

    @classmethod
    def updatedb(cls):
        DnDMonster.update_db()
        DnDSpell.update_db()
        DnDItem.update_db()

    @classmethod
    def generatenpc_image(cls, name=None, gender="gender-fluid", backstory=None):
        prompt = f"A full color illustration of the following {gender} npc from Dungeons and Dragons 5e in a colored penciled animated style: {backstory}"
        filename = f"{slugify(name)}--{datetime.now().toordinal()}"
        resp = OpenAI().generate_image(prompt, name=filename, n=1)
        img_pk = cls.storage.upload(resp[0], "dnd/npcs")
        return img_pk

    @classmethod
    def generatenpc(cls, name=None, summary=None):
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
            "name": "string",
            "age": "int",
            "gender": "string",
            "personality": ["string"],
            "backstory": "string",
            "class": "string",
            "occupation": "string",
            "stats": {
                "strength": "int",
                "dexterity": "int",
                "constitution": "int",
                "intelligence": "int",
                "wisdom": "int",
                "charisma": "int"
            }
        }
        """

        prompt = f"Generate an NPC aged {age} years with the following personality traits: {random.choices(personality, k=3)}"
        npc = OpenAI().generate_text(prompt, primer)
        npc = npc[npc.find("{") : npc.rfind("}") + 1]
        npc = json.loads(npc)
        npc["name"] = name or npc["name"].title()
        npc["backstory"] = summary or npc["backstory"]
        npc["image"] = cls.generatenpc_image()
        return npc

    @classmethod
    def generateencounter(cls, num_players=5, level=1):
        difficulty = [
            "easy",
            "medium",
            "hard",
            "deadly",
            "trivial",
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
        You are a D&D 5e Encounter generator that creates level appropriate random encounters. Respond to prompts only with the following json schema:
        {
            "difficulty": "string",
            "enemies": ["string"],
            "loot": ["string"],
        }
        """
        loot_type = random.choices(loot, weights=[10, 10, 3, 15, 5, 5], k=3)
        prompt = f"Generate an encounter for a party of {num_players} level {level} pcs that is {random.choice(difficulty)} and rewards the following type of loot items: {loot_type}"
        encounter = OpenAI().generate_text(prompt, primer)
        encounter = encounter[encounter.find("{") : encounter.rfind("}") + 1]
        encounter = json.loads(encounter)

        return encounter

    @classmethod
    def generateshop(cls):
        primer = """
        You are a D&D 5e Shop generator that creates random shops. Respond to prompts only with the following json schema:
        {
            "name": "string",
            "shoptype": "string",
            "inventory": {
                "string":"price"
            }
        }
        """
        prompt = "Generate a random shop"
        shop = OpenAI().generate_text(prompt, primer)
        shop = shop[shop.find("{") : shop.rfind("}") + 1]
        shop = json.loads(shop)
        shop["owner"] = cls.generatenpc(
            summary=f"Owner of {shop['name']}, a {shop['shoptype']} shop."
        )
        return shop
