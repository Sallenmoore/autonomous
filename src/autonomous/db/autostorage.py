import json

import tinydb

from autonomous import log


class AutoStorage:
    storage = None

    def __init__(self, *args, **kwargs):  # (1)
        if self.storage is None:
            self.storage = tinydb.TinyDB(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.storage, name)
