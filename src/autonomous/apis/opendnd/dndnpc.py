from autonomous.model.automodel import AutoModel
from autonomous import log
import random
from .. import OpenAI
from autonomous.storage.cloudinarystorage import CloudinaryStorage


class NPC(AutoModel):
    attributes = {
        "name": "",
        "gender": "",
        "image": {"url": "", "asset_id": 0, "raw": None},
        "race": "",
        "desc": "",
        "personality": "",
        "class_name": "",
        "occupation": "",
        "age": 0,
        "inventory": [],
        "str": 0,
        "dex": 0,
        "con": 0,
        "wis": 0,
        "int": 0,
        "cha": 0,
    }

    def generate_image(self):
        resp = OpenAI().generate_image(
            self.get_image_prompt(),
            n=1,
        )
        folder = f"dnd/{self.__class__.__name__.lower()}s"
        self.image = CloudinaryStorage().save(resp[0], folder=folder)
        self.save()

    def get_image_prompt(self):
        description = self.desc or "An npc character"
        style = random.choice(["pixar style 3d", "pencil sketch", "watercolor"])
        return f"A full color {style} of a {self.name} from Dungeons and Dragons 5e - {description}"
