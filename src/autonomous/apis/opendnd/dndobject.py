from . import open5eapi
from autonomous.db.table import Table
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous import log
from slugify import slugify
import os
import sys
import inspect
import requests
from enum import Enum


class DnDObject:
    _api = open5eapi

    def __init__(self, **kwargs):
        self.pk = kwargs.get("pk")
        for k, v in vars(self.__class__).items():
            if not inspect.ismethoddescriptor(v) and not k.startswith("_"):
                # breakpoint()
                setattr(self, k, kwargs.get(k, v))

    def __repr__(self):
        return f"<{self.__dict__}>"

    def serialize(self):
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def save(self):
        record = self.serialize()
        record["slug"] = slugify(record["name"])
        return self._db.save(record)

    def getimage(self):
        if self.image:
            try:
                return CloudinaryStorage().geturl(self.image)
            except Exception as e:
                log(e)
                return None

    @classmethod
    def _update_db(cls, api):
        for updated_record in api.all():
            if record := cls._db.find(name=updated_record["name"]):
                record.update(updated_record)
            else:
                record = updated_record
            model = cls(**record)
            if not model.save():
                raise Exception(f"Failed to save {model}")

    @classmethod
    def all(cls):
        objs = cls._db.all()
        return [cls(**o) for o in objs]

    @classmethod
    def search(cls, **terms):
        objs = cls._db.search(**terms)
        return [cls(**o) for o in objs]

    @classmethod
    def get(cls, id):
        o = cls._db.get(id)
        return cls(**o)


class DnDMonster(DnDObject):
    _db = Table(
        "monsters", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db"
    )
    name = ""
    type = ""
    image = None
    size = ""
    subtype = ""
    alignment = ""
    armor_class = 0
    armor_desc = ""
    hit_points = 0
    hit_dice = ""
    speed = {"walk": 0}
    strength = 21
    dexterity = 8
    constitution = 20
    intelligence = 7
    wisdom = 14
    charisma = 10
    strength_save = None
    dexterity_save = None
    constitution_save = None
    intelligence_save = None
    wisdom_save = None
    charisma_save = None
    perception = 5
    skills = []
    vulnerabilities = []
    resistances = []
    immunities = []
    senses = []
    languages = []
    challenge_rating = 0
    actions = []
    reactions = []
    special_abilities = []
    spell_list = []

    @classmethod
    def update_db(cls):
        cls._update_db(cls._api.DnDMonster)


class DnDSpell(DnDObject):
    _db = Table("spells", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    name = ""
    desc = ""
    image = None
    variations = ""
    range = 0
    ritual = False
    duration: 0
    contentration = False
    casting_time = ""
    level = 0
    school = ""
    archetype = ""
    circles = ""
    damage_dice = ""
    damage_type = ""

    @classmethod
    def update_db(cls):
        cls._update_db(cls._api.DnDSpell)


class DnDItem(DnDObject):
    _db = Table("items", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    name = ""
    desc = ""
    rarity = ""
    cost = 0
    image = None
    description = ""
    attunement = False
    duration: 0
    damage_dice = ""
    damage_type = ""
    weight = 0
    ac_string = ""
    strength_requirement = None
    properties = []

    @classmethod
    def update_db(cls):
        cls._update_db(cls._api.DnDItem)


class DnDPlayer(DnDObject):
    api_url = "https://character-service.dndbeyond.com/character/v5/character"

    _db = Table("players", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")

    attributes = {
        "dnd_id": None,
        "initiative": 0,
        # character traits
        "name": "",
        "image": "",
        "ac": 0,
        "description": "",
        "race": "",
        "speed": 0,
        "class_name": "",
        "age": 0,
        "hp": 0,
        "wealth": [],
        "inventory": [],
        "str": 0,
        "dex": 0,
        "con": 0,
        "wis": 0,
        "int": 0,
        "cha": 0,
        "features": {},
        "spells": {},
        "resistances": [],
    }

    class ArmorType(Enum):
        ARMOR_TYPE_LIGHT = 1
        ARMOR_TYPE_MEDIUM = 2
        ARMOR_TYPE_HEAVY = 3
        ARMOR_TYPE_SHIELD = 4

    class StatType(Enum):
        STR = 1
        DEX = 2
        CON = 3
        INT = 4
        WIS = 5
        CHA = 6

    @staticmethod
    def getmodifier(score: int) -> int:
        """
        Calculate modifier from score
        """
        return (score - 10) // 2

    def updateinfo(self, **kwargs):
        url = f"{self.api_url}/{self.dnd_id}"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()["data"]
        self.parseinfo(**data)

    def parseinfo(self, **kwargs):
        self.name = kwargs.get("name")
        self.age = kwargs.get("age")

        self.image = kwargs.get("decorations")["avatarUrl"]
        if not self.image:
            self.image = kwargs.get("race")["avatarUrl"]

        self.race = kwargs.get("race")["fullName"]
        self.description = kwargs.get("notes")["backstory"]

        self.wealth = kwargs.get("currencies")

        self.class_name = ",".join(
            [c["definition"]["name"] for c in kwargs.get("classes")]
        )

        # Ability Scores
        self.str = self.getstat(DnDPlayer.StatType.STR.value, **kwargs)
        self.dex = self.getstat(DnDPlayer.StatType.DEX.value, **kwargs)
        self.con = self.getstat(DnDPlayer.StatType.CON.value, **kwargs)
        self.wis = self.getstat(DnDPlayer.StatType.WIS.value, **kwargs)
        self.int = self.getstat(DnDPlayer.StatType.INT.value, **kwargs)
        self.cha = self.getstat(DnDPlayer.StatType.CHA.value, **kwargs)

        self.getinventory(**kwargs)
        self.getspeed(**kwargs)
        self.gethp(**kwargs)
        self.getfeatures(**kwargs)
        self.getac(**kwargs)
        self.getresistances(**kwargs)
        self.getspells(**kwargs)
        self.save()

    def getinventory(self, **kwargs):
        self.inventory = []
        for item in kwargs.get("inventory"):
            self.inventory.append(
                {
                    "name": item["definition"]["name"],
                    "description": item["definition"]["description"],
                }
            )

    def getspeed(self, **kwargs):
        self.speed = {}
        try:
            self.speed["walk"] = kwargs["race"]["weightSpeeds"]["normal"]["walk"]
        except KeyError:
            self.speed = 0
            raise KeyError(f'No speed found: {kwargs["race"]["weightSpeeds"]}')

    def gethp(self, **kwargs):
        self.hp = kwargs.get("baseHitPoints") + (9 * (DnDPlayer.getmodifier(self.con)))
        self.hp += kwargs.get("bonusHitPoints") or 0
        self.hp -= kwargs.get("removedHitPoints") or 0
        self.hp += kwargs.get("temporaryHitPoints") or 0

    def getfeatures(self, **kwargs):
        self.features = {}
        for v in kwargs.get("actions").values():
            # log(v)
            if v:
                for option in v:
                    self.features[option["name"]] = option.get("snippet") or option.get(
                        "description"
                    )

        for k, v in kwargs.get("options").items():
            if v:
                for option in v:
                    o = option["definition"]
                    self.features[o["name"]] = o.get("snippet") or o.get("description")

    def getspells(self, **kwargs):
        self.spells = {}
        for v in kwargs.get("spells").values():
            if v:
                for spell in v:
                    o = spell["definition"]
                    self.spells[o["name"]] = o.get("snippet") or o.get("description")

        for v in kwargs.get("classSpells"):
            if v:
                for sp in v["spells"]:
                    o = sp["definition"]
                    self.spells[o["name"]] = o.get("snippet") or o.get("description")

    def getstat(self, stat: int, **kwargs) -> int:
        """
        Calculate maximum hitpoints using hit dice (HD), level and constitution modifier
        """
        score = 0
        stats = kwargs.get("stats")
        for s in stats:
            # log(f"{self.name} - Stats: {s}, {stat}")
            if s["id"] == stat:
                # log(f"{self.name} - Stats: {s}")
                score += s["value"]
        stats = kwargs.get("bonusStats")
        for s in stats:
            if s["id"] == stat:
                # log(f"{self.name} - Stats: {score}, s: {s}")
                score += s["value"] or 0
                # log(f"{self.name} - Stats: {score}, s: {s}")

        stats = kwargs.get("modifiers")
        for category in stats.values():
            # log(f"Modifiers: {s}")
            for s in category:
                if (
                    s.get("entityId") == stat
                    and s.get("type") == "bonus"
                    and "score" in s.get("subType", "")
                ):
                    score += s["value"] or 0
        return score

    def getac(self, **kwargs):
        character_ac = 10 + DnDPlayer.getmodifier(self.dex)
        # log(f"{self.name} - AC: {character_ac}")
        armor_ac = 0
        shield_ac = 0

        equipped_items = []
        for i in kwargs["inventory"]:
            if i["equipped"] and i["definition"]:
                equipped_items.append(i)

        for i in equipped_items:
            if i["definition"].get("armorTypeId"):
                if (
                    DnDPlayer.ArmorType.ARMOR_TYPE_SHIELD.value
                    == i["definition"]["armorTypeId"]
                ):
                    shield_ac += i["definition"]["armorClass"]
                if (
                    DnDPlayer.ArmorType.ARMOR_TYPE_SHIELD.value
                    != i["definition"]["armorTypeId"]
                ):
                    armor_ac += i["definition"]["armorClass"]

        # log(f"{self.name} - Armor AC: {armor_ac + shield_ac}")
        if shield_ac or armor_ac:
            self.ac = max(
                character_ac, armor_ac + shield_ac + DnDPlayer.getmodifier(self.dex)
            )
        else:
            if (
                self.class_name.lower() == "barbarian"
                or self.class_name.lower() == "monk"
            ):
                self.ac += DnDPlayer.getmodifier(self.con)

            if self.class_name.lower() == "monk":
                self.ac += DnDPlayer.getmodifier(self.wis)

        modifiers = kwargs.get("modifiers")

        for category in modifiers.values():
            for s in category:
                if s.get("type") == "bonus" and s.get("subType") == "armor-class":
                    self.ac += s["fixedValue"]

    def getresistances(self, **kwargs):
        modifiers = kwargs.get("modifiers")
        self.resistance = []

        for category in modifiers.values():
            for s in category:
                if s.get("type") == "resistance":
                    self.resistance.append(s["subType"])


class DnDNPC(DnDObject):
    _db = Table("npcs", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    attributes = {
        "dnd_id": None,
        "name": "",
        "image": "",
        "ac": 0,
        "description": "",
        "race": "",
        "class_name": "",
        "age": 0,
        "hp": 0,
        "inventory": [],
        "str": 0,
        "dex": 0,
        "con": 0,
        "wis": 0,
        "int": 0,
        "cha": 0,
    }

    def save(self, **kwargs):
        if image := kwargs.get("image"):
            self.image = CloudinaryStorage().upload(
                image, folder=kwargs.get("img_path", "")
            )
        self.name = kwargs.get("name")
        self.age = kwargs.get("age")
        self.hp = kwargs.get("hp")
        self.race = kwargs.get("race")
        self.description = kwargs.get("backstory")
        self.class_name = kwargs.get("class_name")
        self.str = kwargs.get("strength")
        self.dex = kwargs.get("dexterity")
        self.con = kwargs.get("constitution")
        self.wis = kwargs.get("wisdom")
        self.int = kwargs.get("intelligence")
        self.cha = kwargs.get("charisma")
        self.ac = kwargs.get("ac")

        self.inventory = []
        for item in kwargs.get("inventory"):
            self.inventory.append(
                {
                    "name": item.get("name"),
                    "description": item.get("description"),
                }
            )
        self.inventory = kwargs.get("inventory")
        super().save()


class DnDShop(DnDObject):
    _db = Table("shops", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    name = ""
    owner = None
    description = ""
    inventory = {}

    def save(self, **kwargs):
        self.name = kwargs.get("name")
        self.owner_id = kwargs.get("owner")
        self.description = kwargs.get("backstory")
        self.class_name = kwargs.get("class_name")
        self.inventory = []
        for item in kwargs.get("inventory"):
            self.inventory.append(
                {
                    "name": item.get("name"),
                    "description": item.get("description"),
                }
            )
        self.inventory = kwargs.get("inventory")
        super().save()

    @property
    def owner(self):
        return DnDNPC.get(id=self.owner_id)
