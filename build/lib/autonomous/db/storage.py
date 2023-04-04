import json

import tinydb

from autonomous import log


class AutoStorage(tinydb.storages.Storage):
    def __init__(self, filename):  # (1)
        self.filename = filename

    def read(self):
        with open(self.filename, "a+") as fptr:
            fptr.seek(0, 0)
            data = fptr.read()
            return data

    def write(self, data):
        with open(self.filename, "w") as fptr:
            serialized_data = json.dumps(data)
            fptr.write(serialized_data)

    def close(self):  # (4)
        pass
