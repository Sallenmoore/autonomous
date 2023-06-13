from ..db import db as _database


class ORM:
    def __init__(self, table):
        self._table = _database.get_table(table=table)

    @property
    def table(self):
        return self._table

    def save(self, data):
        return self._table.save(data)

    def get(self, pk):
        return self._table.get(pk)

    def all(self):
        return self._table.all()

    def search(self, **kwargs):
        return self._table.search(**kwargs)

    def find(self, **kwargs):
        return self._table.find(**kwargs)

    def delete(self, pk):
        return self._table.delete(pk)

    def flush_table(self):
        return self._table.clear()
