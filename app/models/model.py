from autonomous.automodel import AutoModel
from autonomous.logger import log


class Utility:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Model(AutoModel):
    # set model default attributes
    autoattr = ["name", "age", "auto", "autolist", "autodict", "autoobj"]

    def __init__(self, **kwargs):
        log(kwargs)

    def serialize(self, data):
        data["autoobj"] = {"data": "Object representation"}
        return data

    def deserialize(self):
        if self.autoobj:
            self.autoobj = Utility(**self.autoobj)
