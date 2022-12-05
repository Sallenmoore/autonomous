import jsonpickle
import tinydb
from autonomous import log

class JSONPickleStorage(tinydb.storages.Storage):
    def __init__(self, filename):  # (1)
        self.filename = filename

    def read(self):
        with open(self.filename, "a+") as fptr:
            fptr.seek(0,0)
            try:
                data = jsonpickle.decode(fptr.read())
                return data
            except Exception as e:
                log(e)
        return None  # (3)

    def write(self, data):
        with open(self.filename, 'w+') as fptr:
            fptr.write(jsonpickle.encode(data))

    def close(self):  # (4)
        pass