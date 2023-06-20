from .basestorage import Storage


class LocalStorage(Storage):
    def save(self, file, path=None):
        pass

    def remove(self, file):
        pass
