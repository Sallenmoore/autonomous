import os


class Storage:
    def __init__(self, path="static"):
        self.path = path

    def geturl(self, key, **kwargs):
        return open(os.path.join(self.path, key))

    def save(self, file):
        pass

    def remove(self, file):
        pass
