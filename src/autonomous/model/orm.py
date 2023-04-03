import uuid

from ..db import db as _database


class ORM:
    def __init__(self, table):
        self._table = _database.get_table(table=table)

    @property
    def _table(self):
        return self._table

    def save(self, data):
        return self._table.save(data)

    def get(self, pk):
        return self._table.get(pk)

    def all(self):
        return self._table.all()

    def search(self, **kwargs):
        return self._table.search(**kwargs)

    def delete(self, pk):
        return self._table.delete(pk)


class TestORM:
    def __init__(self, table):
        self._table = table
        self.db = {}

    @property
    def _table(self):
        return self._table

    def save(self, data):
        if "pk" not in data:
            data['pk'] = uuid.uuid4().hex
        self.db[data["pk"]] = data
        return data["pk"]

    def get(self, pk):
        return self.db.get(pk)

    def all(self):
        return self.db.values()

    def search(self, **kwargs):
        results = []
        for key, value in kwargs.items():
            for item in self.db.values():
                if item[key] == value:
                    results.append(item)
        return list(set(results))

    def delete(self, pk):
        try:
            del self.db[pk]
        except KeyError:
            return pk
        else:
            return None
