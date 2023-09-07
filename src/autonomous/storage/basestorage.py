import os
import slugify


class Storage:
    def __init__(self, path="static"):
        self.path = path

    class Table:
        def __init__(self, name):
            self.name = None

        def insert(self, obj):
            pass

        def update(self, obj):
            pass

        def __len__(self):
            return 0

        def remove(self, pk):
            pass

        def search(self, **kwargs):
            pass

        def get(self, pk):
            pass

        def all(self):
            pass

        def truncate(self):
            pass

    def table(self, name):
        return self.Table(name)
