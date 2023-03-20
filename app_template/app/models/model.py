from autonomous.automodel import AutoModel

# from typing import Optional
from autonomous.logger import log


class Model(AutoModel):
    # set model default attributes
    name: str
    age: int = None
