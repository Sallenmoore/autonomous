"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import json
import uuid

from redis.commands.json.path import Path
from redis.commands.search.field import NumericField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from autonomous import log


class Table:
    """
     _summary_

    _extended_summary_
    """

    def __init__(self, name, attributes, db):
        """
        [summary]
        """
        self._db = db
        self.name = name
        self.schema = attributes
        self.index_name = f"idx:{self.name}"
        self.index = None

    def save(self, obj):
        """
        [summary]
        """
        # log(obj)
        obj["pk"] = obj.get("pk") or str(uuid.uuid4())
        # log(obj, self.count())
        self._db.json().set(f"{self.name}:{obj['pk']}", Path.root_path(), obj)
        return obj["pk"]

    def count(self):
        """
        count _summary_

        _extended_summary_

        :return: _description_
        :rtype: _type_
        """
        result = len(self._db.keys(f"{self.name}:*"))
        return result or 0

    def delete(self, pk):
        """
        [summary]
        """
        self._db.json().delete(f"{self.name}:{pk}", Path.root_path())

    def find(self, **search_terms):
        """
        find _summary_

        _extended_summary_

        :return: _description_
        :rtype: _type_
        """
        result = self.search(**search_terms)
        return result[0] if result else None

    def search(self, **search_terms):
        """
        Returns an list of objects based on passed arguments
        as key/value pairs
        """

        self.index = self._db.ft(self.index_name)
        try:
            self.index.info()
        except Exception as e:
            # log(e)
            schema = []
            for attr, data_type in search_terms.items():
                if attr in self.schema:
                    if isinstance(data_type, str):
                        schema.append(
                            TextField(f"$.{attr}", as_name=attr, sortable=True)
                        )
                    elif isinstance(data_type, (int, float)):
                        schema.append(
                            NumericField(f"$.{attr}", as_name=attr, sortable=True)
                        )
                else:
                    log(f"invalid schema attribute: {attr}")

            self.index = self._db.ft(self.index_name)
            self.index.create_index(
                schema,
                definition=IndexDefinition(
                    prefix=[f"{self.name}:"], index_type=IndexType.JSON
                ),
                temporary=60 * 60 * 24 * 7,  # set indexes to expire in 1 week
            )
        # log(search_terms, self.index_name, self.index.info())
        matches = []
        for k, v in search_terms.items():
            query = Query(f"@{k}:{v}")
            results = self._db.ft(self.index_name).search(query)
            matches += [json.loads(d.json) for d in results.docs]
        return matches

    def get(self, pk):
        """
        [summary]
        """
        try:
            obj = self._db.json().get(f"{self.name}:{pk}", Path.root_path())
        except Exception as e:
            obj = None
            # log(f"no object found with pk:{pk}")
        return obj

    def all(self):
        """
        all _summary_

        _extended_summary_

        :return: _description_
        :rtype: _type_
        """
        keys = self._db.keys(f"{self.name}:*")
        # log(keys)
        return self._db.json().mget(keys, Path.root_path()) if keys else []

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def clear(self):
        """
        clear _summary_

        _extended_summary_
        """
        # breakpoint()
        keys = self._db.keys(f"{self.name}:*")
        return self._db.delete(*keys) if keys else None
