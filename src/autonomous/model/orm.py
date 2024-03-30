from datetime import datetime

from autonomous import log
from autonomous.db.autodb import Database


class ORM:
    _database = Database()

    def __init__(self, name, attributes):
        self.table = self._database.get_table(table=name, schema=attributes)
        self.name = name

    def _replace_pk_with_id(self, data):
        if isinstance(data, dict):
            for key in list(data.keys()):
                if key == "pk":
                    data["_id"] = data.pop("pk")
                else:
                    self._replace_pk_with_id(data[key])
                    # breakpoint()
        elif isinstance(data, list):
            for item in data:
                self._replace_pk_with_id(item)

    def _replace_id_with_pk(self, data):
        if isinstance(data, dict):
            for key in list(data.keys()):
                if key == "_id":
                    data["pk"] = data.pop("_id")
                else:
                    self._replace_id_with_pk(data[key])
                    # breakpoint()
        elif isinstance(data, list):
            for item in data:
                self._replace_id_with_pk(item)

    def save(self, data):
        self._replace_pk_with_id(data)
        if result := self.table.save(data):
            self._replace_id_with_pk(result)
        return result

    def get(self, pk):
        pk = str(pk)
        if result := self.table.get(pk):
            self._replace_id_with_pk(result)
        return result

    def all(self):
        if results := self.table.all():
            self._replace_id_with_pk(results)
        return results

    def search(self, **kwargs):
        self._replace_pk_with_id(kwargs)
        if results := self.table.search(**kwargs):
            self._replace_id_with_pk(results)
        return results

    def find(self, **kwargs):
        # log(kwargs)
        self._replace_pk_with_id(kwargs)
        # log(kwargs)
        if result := self.table.find(**kwargs):
            self._replace_id_with_pk(result)
        # log(result)
        return result

    def random(self):
        if result := self.table.random():
            self._replace_id_with_pk(result)
        return result

    def delete(self, pk):
        pk = str(pk)
        return self.table.delete(_id=pk)

    def flush_table(self):
        return self.table.clear()

    def dbdump(self, directory="./dbbackups"):
        return self._database.dbdump(directory)

    def dbload(self, directory="./dbbackups"):
        return self._database.dbload(directory)
