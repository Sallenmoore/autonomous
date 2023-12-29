"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import json
import random
import re
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
                # self._rules[k] = AutoAttribute("TEXT", default=v)
            elif isinstance(v, (int, float)):
                self._rules[k] = AutoAttribute("NUMERIC", default=v)
            else:
                self._rules[k] = None
        self._index = self._get_index(f"idx:{name}")

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def _get_index(self, name):
        try:
            self._db.ft(name).info()
        except Exception:
            # log(e)
            indexed_attrs = []
            for k, options in self._rules.items():
                if options:
                    if options.type == "TEXT" or options.type == "TAG":
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

    def _encode(self, k, v):
        for r in replacements:
            idx = v.find(r)
            if idx == 0:
                v = v.replace(r, f"\\{r}") if v else ""
            if idx > 0 and v[idx - 1] != f"\\":
                v = v.replace(r, f"\\{r}") if v else ""
        return v

    def _decode(self, v):
        for r in replacements:
            if isinstance(v, str):
                v = v.replace(f"\\{r}", r)
        return v

    def _validate(self, k, v):
        # log(k, v, self._rules)
        if rule := self._rules.get(k):
            if rule.type == "TAG":
                try:
                    assert len(v) < MAXIMUM_TAG_LENGTH
                except AssertionError:
                    raise Exception(
                        f"VALIDATION ERROR: Invalid attribute value. Must be a less than 1024 characters or use a 'TEXT' option, AutoAttribute('TEXT', default=''): {k}:{v}"
                    )
                except TypeError as e:
                    v = ""
                    log(f"VALIDATION ERROR: {e}", f"{k}:{v}")
            elif rule.type == "NUMERIC":
                if v:
                    try:
                        float(v)
                    except TypeError:
                        raise Exception(
                            f"VALIDATION ERROR: Invalid attribute value. Must be a number: {k}:{v}"
                        )

            if rule.required:
                try:
                    assert v is not None
                except AssertionError:
                    raise Exception(
                        f"VALIDATION ERROR: Attribute Required. Must not be 'None': {k}:{v}"
                    )

    def save(self, obj):
        obj["pk"] = obj.get("pk") or str(uuid.uuid4())
        for k, v in obj.items():
            try:
                self._validate(k, v)
                rule = self._rules.get(k)
                if rule and rule.type in ["TEXT"]:
                    obj[k] = self._encode(k, v)
            except Exception as e:
                log(e)
                raise e
        try:
            json_db = self._db.json()
            json_db.set(f"{self.name}:{obj['pk']}", Path.root_path(), obj)
        except TypeError as e:
            # log(obj, "type error")
            raise e
        except Exception as e:
            # log(obj, "other error")
            raise e
        obj = {k: self._decode(v) for k, v in obj.items()}
        # log(obj)
        return obj["pk"]

    def count(self):
        result = len(self._db.keys(f"{self.name}:*"))
        return result or 0

    def delete(self, pk):
        try:
            return self._db.json().delete(f"{self.name}:{pk}", Path.root_path())
        except Exception as e:
            log(e)
            return None

    def find(self, **search_terms):
        result = self.search(**search_terms)
        return result[0] if result else None

    def search(self, **search_terms):
        log(search_terms)
        matches = []

        for k, v in search_terms.items():
            # keys = self._db.keys(f"{self.name}:*")
            # values = self._db.json().mget(keys, f"{Path.root_path()}{k}")
            # log(Path.root_path(), values)
            # for val in keys or []:
            #     if val == v:
            #         matches.append(
            #             self._db.json().get(f"{self.name}:*", Path.root_path())
            #         )
            if ruleset := self._rules[k]:
                v = self._encode(k, v)
                if ruleset.type == "TAG":
                    query_str = f"@{k}:{{'{v}'}}"
                elif ruleset.type == "TEXT":
                    query_str = f"@{k}:( {v} )"
            else:
                raise Exception(f"Can only search indexed fields: {k}:{v}")

            log(query_str)

            query = Query(query_str)
            # breakpoint()
            log(self._index.explain(query))
            response = self._index.search(query)
            log(response)
            matches += [json.loads(d.json) for d in response.docs]
        log(matches)
        results = {
            obj["pk"]: {k: self._decode(v) for k, v in obj.items()} for obj in matches
        }
        results = list(results.values())
        log(results)
        return results

    def get(self, pk):
        # log(pk)
        if not pk or pk == "None":
            return None

        if obj := self._db.json().get(f"{self.name}:{pk}", Path.root_path()):
            for k, v in obj.items():
                for r in replacements:
                    if isinstance(v, str):
                        obj[k] = self._decode(v)
            return obj
        return None

    def all(self):
        keys = self._db.keys(f"{self.name}:*")
        # log(keys)
        objs = self._db.json().mget(keys, Path.root_path()) if keys else []
        for i, obj in enumerate(objs):
            objs[i] = {k: self._decode(v) for k, v in obj.items()}
        return objs

    def random(self):
        keys = self._db.keys(f"{self.name}:*")
        try:
            key = random.choice(keys).split(":")[-1]
        except Exception as e:
            # log(e, f"Table '{self.name}' is empty.")
            return None
        else:
            return self.get(key)

    def clear(self):
        # breakpoint()
        keys = self._db.keys(f"{self.name}:*")
        return self._db.delete(*keys) if keys else None
