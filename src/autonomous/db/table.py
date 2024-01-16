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
from typing import Optional, Pattern

from redis.commands.json.path import Path
from redis.commands.search.field import NumericField, TagField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from autonomous import log
from autonomous.model.autoattribute import AutoAttribute

MAXIMUM_TAG_LENGTH = 1025


class AutoEscaper:
    """
    Escape punctuation within an input string.
    """

    # Characters that RediSearch requires us to escape during queries.
    # Source: https://redis.io/docs/stack/search/reference/escaping/#the-rules-of-text-field-tokenization

    escaped_chars = r"[,.<>{}\[\]\\\"\':;!@#$%^&*()\-+=~\/ ]"

    @classmethod
    def encode(cls, value: str) -> str:
        # log(value)
        for char in cls.escaped_chars:
            value = value.replace(char, f"\\{char}")
        # log(value)
        return value

    @classmethod
    def decode(cls, value: str) -> str:
        # log(value)
        for char in cls.escaped_chars:
            value = value.replace(f"\\{char}", char)
        # log(value)
        return value


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

    def _encode(self, record):
        for k, v in record.items():
            if rule := self._rules.get(k):
                if rule.type in ["TEXT", "TAG"]:
                    record[k] = AutoEscaper.encode(v)
        return record

    def _decode(self, record):
        for k, v in record.items():
            if self._rules.get(k) and self._rules.get(k).type in ["TEXT", "TAG"]:
                try:
                    record[k] = AutoEscaper.decode(v)
                except Exception as e:
                    log(e, k, v)
        return record

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
            except Exception as e:
                # log(e)
                raise e
        # log(obj)
        obj = self._encode(obj)
        # log(obj)
        try:
            json_db = self._db.json()
            json_db.set(f"{self.name}:{obj['pk']}", Path.root_path(), obj)
        except TypeError as e:
            # log(obj, "type error")
            raise e
        except Exception as e:
            # log(obj, "other error")
            raise e
        obj = self._decode(obj)
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

    def fastsearch(self, **search_terms):
        """Not working like I want it to"""
        matches = []
        for k, v in search_terms.items():
            if ruleset := self._rules[k]:
                v = AutoEscaper.encode(v)
                if ruleset.type == "TAG":
                    query_str = f"@{k}:{v}"
                elif ruleset.type == "TEXT":
                    query_str = f"@{k}:( {v} )"
            else:
                raise Exception(f"Can only search indexed fields: {k}:{v}")

            query = Query(query_str)
            # breakpoint()
            response = self._index.search(query)
            # log(
            #     Path.root_path(),
            #     search_terms,
            #     query_str,
            #     self._index.explain(query),
            #     response,
            #     self.all(),
            # )
            matches += [json.loads(d.json) for d in response.docs]
        results = [self._decode(obj) for obj in matches]
        # log(results)
        return results

    def search(self, **search_terms):
        """
        Temporary serach implementation until I cna figure out stupid RediJSON search
        This is currently faster than the RediJSON search
        """
        return self.fastsearch(**search_terms)
        # return [
        #     obj
        #     for obj in self.all()
        #     for term, val in search_terms.items()
        #     if val in obj.get(term)
        # ]

    def get(self, pk):
        # log(pk)
        if not pk or pk == "None":
            return None
        if obj := self._db.json().get(f"{self.name}:{pk}", Path.root_path()):
            return self._decode(obj)
        return None

    def all(self):
        keys = self._db.keys(f"{self.name}:*")
        # log(keys)
        objs = self._db.json().mget(keys, Path.root_path()) if keys else []
        return [self._decode(obj) for obj in objs]

    def random(self):
        keys = self._db.keys(f"{self.name}:*")
        log(keys)
        try:
            key = random.choice(keys)
            log(key)
        except Exception as e:
            log(e, f"Table '{self.name}' is empty.")
            return None
        else:
            result = self.get(key.split(":")[-1])
            log(result)
            return result

    def clear(self):
        # breakpoint()
        keys = self._db.keys(f"{self.name}:*")
        return self._db.delete(*keys) if keys else None
