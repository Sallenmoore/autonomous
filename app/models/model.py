from autolib.automodel import AutoModel
from autolib.logger import log


class Model(AutoModel):
    # set model default attributes
    autoattr = ["name"]

    def __init__(self, **kwargs):
        log(kwargs)
