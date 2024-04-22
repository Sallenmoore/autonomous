"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""

import json
import random

from bson.objectid import ObjectId

from autonomous import log
from autonomous.model.autoattribute import AutoAttribute


class Table:
    def __init__(self, name, attributes, db):
        self._db = db[name]
        self.name = name
        # log(attributes)
        self._rules = {}

        for k, v in attributes.items():
            if isinstance(v, AutoAttribute):
                self._rules[k] = v
            elif isinstance(v, str):
                self._rules[k] = AutoAttribute("TEXT", default=v)
            elif isinstance(v, (int, float)):
                self._rules[k] = AutoAttribute("NUMERIC", default=v)
            else:
                self._rules[k] = None
        self._index = self._get_index(f"idx:{name}")

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def _get_index(self, name):
        pass

    def _validate(self, k, v):
        # log(k, v, self._rules)
        if rule := self._rules.get(k):
            if rule.type == "NUMERIC":
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
        for k, v in obj.items():
            try:
                self._validate(k, v)
            except Exception as e:
                # log(e)
                raise e

        if obj_id := obj.get("_id"):
            obj["_id"] = ObjectId(obj_id)
            self._db.replace_one({"_id": obj["_id"]}, obj, True)
        else:
            obj.pop("_id", None)
            obj["_id"] = self._db.insert_one(obj).inserted_id
        return str(obj["_id"])

    def count(self):
        return self._db.count_documents({})

    def delete(self, _id):
        try:
            return self._db.delete_one({"_id": ObjectId(_id)}).acknowledged
        except Exception as e:
            log(e)

    def _convert_to_dot_notation(self, search_terms, fuzzy_search=False, prefix=""):
        dot_notation = {}
        for key, value in search_terms.items():
            if isinstance(value, dict):
                dot_notation.update(
                    self._convert_to_dot_notation(
                        value, fuzzy_search=fuzzy_search, prefix=f"{prefix}{key}."
                    )
                )
            else:
                if fuzzy_search and isinstance(value, str):
                    dot_notation[f"{prefix}{key}"] = {"$regex": value, "$options": "i"}
                else:
                    dot_notation[f"{prefix}{key}"] = value
        return dot_notation

    def find(self, **search_terms):
        search_terms = self._convert_to_dot_notation(search_terms)
        result = self._db.find_one(search_terms)
        if result:
            result["_id"] = str(result["_id"])
            return result

    def search(self, **search_terms):
        fuzzy_search = search_terms.pop("_FUZZY_SEARCH", False)
        search_terms = self._convert_to_dot_notation(
            search_terms, fuzzy_search=fuzzy_search
        )
        result = self._db.find(search_terms) or []

        objs = []
        for o in result:
            o["_id"] = str(o["_id"])
            objs.append(o)
        # log(search_terms, fuzzy_search, objs)
        return objs

    def get(self, _id):
        if not _id or _id == "None":
            return None
        if o := self._db.find_one({"_id": ObjectId(_id)}):
            o["_id"] = str(o["_id"])
            return o

    def all(self):
        objs = []
        for o in self._db.find():
            o["_id"] = str(o["_id"])
            objs.append(o)
        return objs

    def random(self):
        keys = [o for o in self._db.find({}, projection=["_id"])]
        # log(keys)
        try:
            key = random.choice(keys)
        except Exception as e:
            # log(e, f"Table '{self.name}' is empty.")
            return None
        else:
            result = self.get(str(key["_id"]))
            # log(result)
            return result

    def clear(self):
        # breakpoint()
        return self._db.drop()
