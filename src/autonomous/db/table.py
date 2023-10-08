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

replacements = [
    ",",
    ".",
    "<",
    ">",
    "{",
    "}",
    "[",
    "]",
    '"',
    "'",
    ":",
    ";",
    "!",
    "@",
    "#",
    "$",
    "%",
    "^",
    "&",
    "*",
    "(",
    ")",
    "-",
    "+",
    "=",
    "~",
]


def escape_value(value):
    """
    [summary]
    """
    if isinstance(value, str):
        for v in replacements:
            idx = value.find(v)
            if idx == 0:
                value = value.replace(v, f"\\{v}")
            if idx > 0 and value[idx - 1] != "\\":
                value = value.replace(v, f"\\{v}")
    return value


def deescape_value(value):
    """
    [summary]
    """
    if isinstance(value, str):
        for v in replacements:
            value = value.replace(f"\\{v}", v)
    return value


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

    @property
    def index(self):
        """
        [summary]
        """
        try:
            self._db.ft(self.index_name).info()
        except Exception as e:
            # log(e)
            schema = []
            for attr, data_type in self.schema.items():
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
                    log(f"invalid index attribute: {attr}")

            self._db.ft(self.index_name).create_index(
                schema,
                definition=IndexDefinition(
                    prefix=[f"{self.name}:"], index_type=IndexType.JSON
                ),
                temporary=60 * 60 * 24 * 7,  # set indexes to expire in 1 week
            )
        return self._db.ft(self.index_name)

    def save(self, obj):
        """
        [summary]
        """
        # log(obj)
        obj["pk"] = obj.get("pk") or str(uuid.uuid4())
        obj = {k: escape_value(v) for k, v in obj.items()}
        # log(obj, self.count())
        self._db.json().set(f"{self.name}:{obj['pk']}", Path.root_path(), obj)
        obj = {k: deescape_value(v) for k, v in obj.items()}
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
        pk = escape_value(pk)
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

        # log(search_terms, self.index_name, self.index.info())
        matches = []
        for k, v in search_terms.items():
            v = escape_value(v)
            query = Query(f"@{k}:{v}")
            results = self.index.search(query)
            matches += [json.loads(d.json) for d in results.docs]
        for i, obj in enumerate(matches):
            matches[i] = {k: deescape_value(v) for k, v in obj.items()}
        return matches

    def get(self, pk):
        """
        [summary]
        """
        pk = escape_value(pk)
        try:
            obj = self._db.json().get(f"{self.name}:{pk}", Path.root_path())
        except Exception as e:
            obj = None
            # log(f"no object found with pk:{pk}")
        if obj:
            obj = {k: deescape_value(v) for k, v in obj.items()}
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
        objs = self._db.json().mget(keys, Path.root_path()) if keys else []
        for i, obj in enumerate(objs):
            objs[i] = {k: deescape_value(v) for k, v in obj.items()}
        return objs

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
