import json
import os
import pprint

import firebase_admin
from firebase_admin import credentials, db

from . import autoencoder, log

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(
        credentials.Certificate(os.getenv("FIREBASE_KEY_FILE")),
        {"databaseURL": os.getenv("FIREBASE_URL")},
    )


class AutoModel:
    autoattr = []

    def __new__(cls, *args, **kwargs):

        obj = super().__new__(cls)

        obj._pk = kwargs.get("_pk", kwargs["_ref"].key if "_ref" in kwargs else None)
        obj._ref = cls.table().child(str(obj._pk)) if obj._pk else None
        kwargs |= obj._ref.get() if obj._ref else {}

        for k in cls.autoattr:
            setattr(obj, k, None)

        kwargs = autoencoder.AutoEncoder().decode(kwargs)
        for k, v in kwargs.items():
            setattr(obj, k, v)
        obj.deserialize()
        return obj

    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def serialize(self, data):
        return data

    def deserialize(self):
        pass

    @classmethod
    def table(cls):
        if not hasattr(cls, "_table"):
            ref = db.reference(os.getenv("APP_NAME"))
            cls._table = ref.child(cls.__name__.lower())
        return cls._table

    @property
    def pk(self):
        if not hasattr(self, "_pk"):
            self._pk = None
        return self._pk

    @pk.setter
    def pk(self, value):
        self._pk = value

    def save(self):
        # filter invalid attributes and other models and save them
        save_data = autoencoder.AutoEncoder().default(self)
        # update existing record
        if self._ref:
            self._ref.set(save_data)
        # save new record
        else:
            self._ref = self.table().push(value=save_data)
            self._ref.update({"_pk": self._ref.key})

        # set key
        self._pk = self._ref.key
        return self._pk

    def delete(self):
        return self._ref.delete()

    @classmethod
    def get(cls, id):
        ref = cls.table().child(str(id))
        if data := ref.get():
            data["_pk"] = ref.key
            data["_ref"] = ref
            obj = cls(**data)
            return obj

    @classmethod
    def all(cls):
        data = cls.table().get()
        objs = []
        if data:
            for k, v in data.items():
                if "_pk" not in v:
                    v["_pk"] = k
                objs.append(cls(**v))
        return objs

    @classmethod
    def search(cls, **kwargs):
        objs_dicts = []
        for k, v in kwargs.items():
            objs_dicts.append(cls.table().order_by_child(k).equal_to(v).get())
        return [cls(**o) for o in objs_dicts]

    @classmethod
    def clear_table(cls):
        cls.table().delete()
