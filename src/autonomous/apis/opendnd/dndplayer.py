from autonomous.model.automodel import AutoModel
from autonomous import log
from .dndbeyondapi import DnDBeyondAPI
import io
from .. import OpenAI
from autonomous.storage.cloudinarystorage import CloudinaryStorage
from validators.url import url as urlvalidator
from enum import Enum


class Player(AutoModel):
    attributes = {
        "dnd_id": None,
        "initiative": 0,
        # character traits
        "name": "",
        "image": {},
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

        data = DnDBeyondAPI.getcharacter(self.dnd_id)

        try:
            results = self.table().search(dnd_id=self.dnd_id)[0]
        except StopIteration:
            log("Player not found. Assuming new player.")
        else:
            self.pk = results["pk"]

        if data.get("image") and not self.image.get("url"):
            self.image = CloudinaryStorage().save(self.image, folder="dnd/players")
        else:
            data["image"] = self.image

        self.__dict__.update(data)
        # log(self)
        self.save()
