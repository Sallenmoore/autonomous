from autonomous.model.automodel import AutoModel
from autonomous import log
from .dndbeyondapi import DnDBeyondAPI
from slugify import slugify
from autonomous.storage.cloudinarystorage import CloudinaryStorage


class Player(AutoModel):
    attributes = {
        "dnd_id": None,
        "initiative": 0,
        # character traits
        "name": "",
        "image": {"url": "", "asset_id": 0, "raw": None},
        "ac": 0,
        "desc": "",
        "race": "",
        "speed": {},
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

    def updateinfo(self, **kwargs):
        assert self.dnd_id, "Player must have a dnd_id"
        if data := DnDBeyondAPI.getcharacter(self.dnd_id):
            if results := self.table().find(dnd_id=self.dnd_id):
                self.pk = results["pk"]

            if data["image"]["url"] and data["image"]["url"] != self.image.get("url"):
                self.image = CloudinaryStorage().save(
                    data["image"]["url"], folder=f"dnd/players/{slugify(self.name)}"
                )
            del data["image"]

            self.__dict__.update(data)
            # log(self)
            self.save()
        return data
