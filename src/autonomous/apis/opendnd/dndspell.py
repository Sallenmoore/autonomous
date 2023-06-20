from .dndobject import DnDObject
from autonomous import logger
import random


class Spell(DnDObject):
    attributes = {
        "name": "",
        "image": {"url": "", "asset_id": 0, "raw": None},
        "desc": "",
        "variations": "",
        "range": 0,
        "ritual": False,
        "duration": 0,
        "concentration": False,
        "casting_time": "",
        "level": 0,
        "school": "",
        "archetype": "",
        "circles": "",
        "damage_dice": "",
        "damage_type": "",
    }

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
