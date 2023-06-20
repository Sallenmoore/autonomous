from .dndobject import DnDObject
from autonomous import log
import random


class Monster(DnDObject):
    attributes = {
        "name": "",
        "image": {"url": "", "asset_id": 0, "raw": None},
        "desc": "",
        "type": "",
        "size": "",
        "subtype": "",
        "alignment": "",
        "armor_class": 0,
        "armor_desc": "",
        "hit_points": 0,
        "hit_dice": "",
        "speed": {"walk": 0},
        "strength": 21,
        "dexterity": 8,
        "constitution": 20,
        "intelligence": 7,
        "wisdom": 14,
        "charisma": 10,
        "strength_save": None,
        "dexterity_save": None,
        "constitution_save": None,
        "intelligence_save": None,
        "wisdom_save": None,
        "charisma_save": None,
        "perception": 5,
        "skills": [],
        "vulnerabilities": [],
        "resistances": [],
        "immunities": [],
        "senses": [],
        "languages": [],
        "challenge_rating": 0,
        "actions": [],
        "reactions": [],
        "special_abilities": [],
        "spell_list": [],
    }

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
