from utils.automodel import AutoModel


class Model(AutoModel):
    def __init__(self, **kwargs):
        self.__dict__ |= kwargs
