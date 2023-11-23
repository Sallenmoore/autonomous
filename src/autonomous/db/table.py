"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import json
import random
import uuid

from redis.commands.json.path import Path
from redis.commands.search.field import NumericField, TagField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from autonomous import log
from autonomous.model.autoattribute import AutoAttribute

MAXIMUM_TAG_LENGTH = 1025
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
    " ",
]


class Table:
    def __init__(self, name, attributes, db):
        self._db = db
        self.name = name
        # log(attributes)
        self._rules = {}

        for k, v in attributes.items():
            if isinstance(v, AutoAttribute):
                self._rules[k] = v
            elif isinstance(v, str):
                self._rules[k] = AutoAttribute("TAG", default=v)
            elif isinstance(v, (int, float)):
                self._rules[k] = AutoAttribute("NUMERIC", default=v)
            else:
                self._rules[k] = None
        self._index = self._get_index(f"idx:{name}")

    def _get_index(self, name):
        try:
            self._db.ft(name).info()
        except Exception as e:
            # log(e)
            indexed_attrs = []
            for k, options in self._rules.items():
                if options:
                    if options.type == "TEXT":
                        indexed_attrs.append(
                            TextField(f"$.{k}", as_name=k, sortable=True)
                        )
                    elif options.type == "TAG":
                        indexed_attrs.append(
                            TagField(f"$.{k}", as_name=k, sortable=True)
                        )
                    elif options.type == "NUMERIC":
                        indexed_attrs.append(
                            NumericField(f"$.{k}", as_name=k, sortable=True)
                        )
            self._db.ft(name).create_index(
                indexed_attrs,
                definition=IndexDefinition(
                    prefix=[f"{self.name}:"], index_type=IndexType.JSON
                ),
                temporary=60 * 60 * 24 * 7,  # set indexes to expire in 1 week
            )
        return self._db.ft(name)

    def _validate(self, k, v, decode=False, encode=False):
        # log(k, v, self._rules)
        if rule := self._rules[k]:
            if rule.type in ["TEXT", "TAG"]:
                if decode:
                    for r in replacements:
                        v = v.replace(f"\\{r}", r) if v else ""
                elif encode:
                    if isinstance(v, str):
                        for r in replacements:
                            idx = v.find(r)
                            if idx == 0:
                                v = v.replace(r, f"\\{r}") if v else ""
                            if idx > 0 and v[idx - 1] != "\\":
                                v = v.replace(r, f"\\{r}") if v else ""

                if rule.type == "TAG":
                    try:
                        assert len(v) < MAXIMUM_TAG_LENGTH
                    except AssertionError:
                        raise Exception(
                            f"Invalid attribute value. Must be a less than 1024 characters or use a 'TEXT' option, AutoAttribute('TEXT', default=''): {k}:{v}"
                        )
                    except TypeError as e:
                        v = ""
                        log(f"{e}", f"{k}:{v}")
            elif rule.type == "NUMERIC":
                if v:
                    try:
                        float(v)
                    except TypeError:
                        raise Exception(
                            f"Invalid attribute value. Must be a number: {k}:{v}"
                        )

            if rule.required:
                try:
                    assert v is not None
                except AssertionError:
                    raise Exception(
                        f"Invalid attribute value. Must not be 'None': {k}:{v}"
                    )
        return v

    def save(self, obj):
        # log(obj)
        obj["pk"] = obj.get("pk") or str(uuid.uuid4())
        for k, v in obj.items():
            if rule := self._rules.get(k):
                if rule.type == "TEXT":
                    obj[k] = self._validate(k, v, encode=True)
                else:
                    obj[k] = self._validate(k, v)
        try:
            json_db = self._db.json()
            json_db.set(f"{self.name}:{obj['pk']}", Path.root_path(), obj)
        except Exception as e:
            raise e
        obj = {k: self._validate(k, v, decode=True) for k, v in obj.items()}
        return obj["pk"]

    def count(self):
        result = len(self._db.keys(f"{self.name}:*"))
        return result or 0

    def delete(self, pk):
        return self._db.json().delete(f"{self.name}:{pk}", Path.root_path())

    def find(self, **search_terms):
        result = self.search(**search_terms)
        return result[0] if result else None

    def search(self, **search_terms):
        # log(search_terms, self.index_name, self.index.info())
        matches = []

        for k, v in search_terms.items():
            try:
                v = self._validate(k, v, encode=True)
            except KeyError:
                raise Exception(f"Can only search indexed fields: {k}:{v}")

            query_str = f"@{k}:{v}"
            ruleset = self._rules[k]
            if ruleset and ruleset.type == "TAG":
                query_str = "@" + str(k) + ":{" + str(v) + "}"
            elif ruleset and ruleset.type == "TEXT":
                query_str = f"@{k}:({v})"

            # log(query_str)

            query = Query(query_str)
            # breakpoint()

            results = self._index.search(query)
            # log(results)
            matches += [json.loads(d.json) for d in results.docs]

        results = {
            obj["pk"]: {k: self._validate(k, v, decode=True) for k, v in obj.items()}
            for obj in matches
        }

        return list(results.values())

    def get(self, pk):
        try:
            obj = self._db.json().get(f"{self.name}:{pk}", Path.root_path())
            assert obj
        except Exception as e:
            obj = None
        else:
            for k in obj:
                for r in replacements:
                    if isinstance(obj[k], str):
                        obj[k] = obj[k].replace(f"\\{r}", r)
        return obj

    def all(self):
        keys = self._db.keys(f"{self.name}:*")
        # log(keys)
        objs = self._db.json().mget(keys, Path.root_path()) if keys else []
        for i, obj in enumerate(objs):
            objs[i] = {k: self._validate(k, v, decode=True) for k, v in obj.items()}
        return objs

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def random(self):
        keys = self._db.keys(f"{self.name}:*")
        key = random.choice(keys).split(":")[-1]
        return self.get(key)

    def clear(self):
        # breakpoint()
        keys = self._db.keys(f"{self.name}:*")
        return self._db.delete(*keys) if keys else None
