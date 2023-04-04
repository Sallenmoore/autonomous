from autonomous import log
from autonomous.model.automodel import AutoModel


class Model(AutoModel):
    # set model default attributes
    attributes = {
        "name": "",
        "age": None,
    }
