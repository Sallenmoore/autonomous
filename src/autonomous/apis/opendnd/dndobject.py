from . import open5eapi
from autonomous.db.table import Table
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from autonomous.model.automodel import AutoModel
from autonomous import log
from slugify import slugify
from validators.url import url as urlvalidator
import os
import sys
import markdown
import random
import requests
from enum import Enum
from .. import OpenAI


class DnDObject:
    _api = open5eapi
    _storage = CloudinaryStorage()
    name = ""
    image = {"url": "", "asset_id": 0, "raw": None}
    desc = ""

    def __init__(self, **kwargs):
        self.pk = kwargs.get("pk")
        attributes = dict(vars(DnDObject)) | dict(vars(self.__class__))
        attributes = {k: v for k, v in attributes.items() if not k.startswith("_")}
        # log(attributes)
        for k, v in kwargs.items():
            if k in list(attributes.keys()):
                setattr(self, k, v)

    def __repr__(self):
        return f"<{self.__dict__}>"

    def serialize(self):
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def delete(self):
        return self._db.delete(pk=self.pk)

    def save(self):
        if self.image.get("raw"):
            folder = f"dnd/{self.__class__.__name__.lower()}s/{self.slug}"
            self.image = self._storage.save(self.image["raw"], folder=folder)
        self.slug = slugify(self.name)
        record = self.serialize()
        self.pk = self._db.save(record)
        return self.pk

    def generate_image(self):
        resp = OpenAI().generate_image(
            self.get_image_prompt(),
            n=1,
        )
        folder = f"dnd/{self.__class__.__name__.lower()}s"
        self.image = self._storage.save(resp[0], folder=folder)
        self.save()

    def get_image_prompt(self):
        return f"A full color portrait of a {self.name} from Dungeons and Dragons 5e - {self.desc}"

    def _api_update(self, api):
        for record in api.all():
            if record["slug"] == self.slug:
                self.__dict__.update(record)
                self.save()

    @classmethod
    def _update_db(cls, api):
        for updated_record in api.all():
            if record := cls._db.find(slug=slugify(updated_record["name"])):
                record.update(updated_record)
            else:
                record = updated_record
            model = cls(**record)
            if not model.save():
                raise Exception(f"Failed to save {model}")
            # else:
            #     log(f"Saved {model.name}")

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


class Monster(DnDObject):
    _db = Table(
        "monsters", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db"
    )
    type = ""
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

    @classmethod
    def get_image_prompt(self):
        description = self.desc or random.choice(
            [
                "A renaissance portrait",
                "An action movie poster",
                "Readying for battle",
            ]
        )
        style = random.choice(
            [
                "The Rusted Pixel style digital",
                "Albrecht Dürer style photorealistic pencil sketch",
                "William Blake style watercolor",
            ]
        )
        return f"A full color {style} portrait of a {self.name} from Dungeons and Dragons 5e - {description}"


class Spell(DnDObject):
    _db = Table("spells", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    variations = ""
    range = 0
    ritual = False
    duration: 0
    concentration = False
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

    @classmethod
    def get_image_prompt(self):
        description = self.desc or "A magical spell"
        style = random.choice(
            [
                "The Rusted Pixel style digital",
                "Albrecht Dürer style photorealistic pencil sketch",
                "William Blake style watercolor",
            ]
        )
        return f"A full color {style} of a {self.name} from Dungeons and Dragons 5e - {description}"


class Item(DnDObject):
    _db = Table("items", path=f"{os.path.dirname(sys.modules[__name__].__file__)}/db")
    name = ""
    rarity = ""
    cost = 0
    attunement = False
    duration: 0
    damage_dice = ""
    damage_type = ""
    weight = 0
    ac_string = ""
    strength_requirement = None
    properties = []
    tables = []

    def __init__(self, **kwargs):
        kwargs["desc"] = markdown.markdown(kwargs.get("desc") or "")
        super().__init__(**kwargs)

    @classmethod
    def update_db(cls):
        cls._update_db(cls._api.DnDItem)

    @classmethod
    def get_image_prompt(self):
        description = self.desc or "An equipable item"
        style = random.choice(
            [
                "The Rusted Pixel style digital",
                "Albrecht Dürer style photorealistic pencil sketch",
                "William Blake style watercolor",
            ]
        )
        return f"A full color {style} of a {self.name} from Dungeons and Dragons 5e - {description}"
