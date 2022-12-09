import jsonpickle
import tinydb
from autonomous import log

class JSONPickleStorage(tinydb.storages.Storage):
    def __init__(self, filename):  # (1)
        self.filename = filename

    def __setattr__(self, k, v):
        super().__setattr__(k, v)

    def read(self):
        with open(self.filename, "a+") as fptr:
            fptr.seek(0,0)
            data = fptr.read()
            return jsonpickle.decode(data) if data else None

    def write(self, data):
        with open(self.filename, 'w') as fptr:
            fptr.write(jsonpickle.encode(data))

    def close(self):  # (4)
        pass