from ..db.autodb import Database


class ORM:
    _database = Database()

    def __init__(self, model):
        # breakpoint()
        table_name = model._table_name or model.__name__
        self.table = self._database.get_table(table=table_name, schema=model.attributes)
        self.name = self.table.name

    def save(self, data):
        return self.table.save(data)

    def get(self, pk):
        return self.table.get(pk)

    def all(self):
        return self.table.all()

    def search(self, **kwargs):
        return self.table.search(**kwargs)

    def find(self, **kwargs):
        return self.table.find(**kwargs)

    def delete(self, pk):
        return self.table.delete(pk)

    def flush_table(self):
        return self.table.clear()
