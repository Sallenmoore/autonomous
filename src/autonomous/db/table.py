"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import json
import random
import uuid

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
        if obj.get("_id"):
            self._db.replace_one({"_id": obj["_id"]}, obj, True)
        else:
            obj.pop("_id", None)
            obj["_id"] = self._db.insert_one(obj).inserted_id
        return obj["_id"]

    def count(self):
        return self._db.count_documents({})

    def delete(self, _id):
        try:
            return self._db.test.delete_one({"_id": _id}).acknowledged
        except Exception as e:
            log(e)
            return None

    def find(self, **search_terms):
        result = self._db.find_one(search_terms)
        return result if result else None

    def search(self, **search_terms):
        """Not working like I want it to"""
        result = self._db.find(search_terms)
        return [o for o in result] if result else None

    def get(self, _id):
        if not _id or _id == "None":
            return None
        if obj := self._db.find_one({"_id": _id}):
            return obj
        return None

    def all(self):
        return [o for o in self._db.find()]

    def random(self):
        keys = [o for o in self._db.find({}, projection=["_id"])]
        # log(keys)
        try:
            key = random.choice(keys)
        except Exception as e:
            # log(e, f"Table '{self.name}' is empty.")
            return None
        else:
            result = self.get(key["_id"])
            # log(result)
            return result

    def clear(self):
        # breakpoint()
        return self._db.drop()
