from abc import ABC


class Database(ABC):

    def get_instance(self, **kwargs):
        return None

    def save(self, obj, **kwargs):
        raise NotImplementedError

    def delete(self, key, **kwargs):
        raise NotImplementedError

    def all(self):
        raise NotImplementedError

    def get(self, key, **kwargs):
        raise NotImplementedError

    def search(self, **kwargs):
        raise NotImplementedError

    def clear_database(self):
        raise NotImplementedError
