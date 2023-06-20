from .dndobject import DnDObject
from autonomous import logger
import random
import markdown


class Item(DnDObject):
    attributes = {
        "name": "",
        "image": {"url": "", "asset_id": 0, "raw": None},
        "desc": "",
        "rarity": "",
        "cost": 0,
        "attunement": False,
        "duration": "",
        "damage_dice": "",
        "damage_type": "",
        "weight": 0,
        "ac_string": "",
        "strength_requirement": None,
        "properties": [],
        "tables": [],
    }

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
