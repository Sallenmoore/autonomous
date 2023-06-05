import os
import slugify


class Storage:
    def __init__(self, path="static"):
        self.path = path

    def geturl(self, key, **kwargs):
        return open(os.path.join(self.path, key))

    def save(self, file, path=None):
        pass

    def remove(self, file):
        pass

    @classmethod
    def getfileid(cls, file):
        filename = os.path.basename(file)
        id = os.path.splitext(filename)[0]
        return slugify(id)
