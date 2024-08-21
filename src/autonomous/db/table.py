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


class Table:
    def __init__(self, name, attributes, db):
        self._db = db[name]
        self.name = name
        # log(attributes)
        self._index = self._get_index(f"idx:{name}")

    def __str__(self):
        return json.dumps(self.all(), indent=4)

    def _get_index(self, name):
        pass

    def save(self, obj):
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
        try:
            if o := self._db.find_one({"_id": ObjectId(_id)}):
                o["_id"] = str(o["_id"])
        except Exception as e:
            return None
            # log(e, f"Object '{_id}' not found in '{self.name}'")
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
