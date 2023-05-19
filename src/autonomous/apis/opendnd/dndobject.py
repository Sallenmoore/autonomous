from . import open5eapi
from autonomous.db.table import Table
from autonomous import log
from slugify import slugify
import os
import sys
import inspect


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

    def save(self):
        record = {k: v for k, v in vars(self).items() if not k.startswith("_")}
        record["slug"] = slugify(record["name"])
        return self._db.save(record)

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
    armor_class: 0
    armor_desc = ""
    hit_points: 0
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
