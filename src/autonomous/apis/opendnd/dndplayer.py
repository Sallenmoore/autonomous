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
        "image": "",
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
        results = self.search(dnd_id=self.dnd_id)
        if results:
            self.pk = results[0].pk

        data = DnDBeyondAPI.getcharacter(self.dnd_id)
        self.__dict__.update(data)
        log(self)
        self.img()
        self.save()

    def img(self):
        if isinstance(self.image, str) and not urlvalidator(self.image):
            try:
                self.image = CloudinaryStorage().geturl(self.image)
            except Exception as e:
                log(e)
                return ""
        elif isinstance(self.image, io.BufferedReader):
            self.image = CloudinaryStorage().upload(self.image, folder="dnd/players")
        return self.image
