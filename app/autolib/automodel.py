import json
import os
import pprint

import firebase_admin
from autolib import log
from autolib.autoencoder import AutoEncoder
from firebase_admin import credentials, db

cred = credentials.Certificate(os.getenv("FIREBASE_KEY_FILE"))
firebase_admin.initialize_app(cred, {"databaseURL": os.getenv("FIREBASE_URL")})


class AutoModel:
    _auto_models = {}
    autoattr = []

    def __new__(cls, *args, **kwargs):

        pk = kwargs["_ref"].key if kwargs.get("_ref") else kwargs.get("pk")
        _ref = cls.table().child(str(pk)) if pk else None

        if _ref:
            result = _ref.get()
            kwargs = result | kwargs

        kwargs["_ref"] = _ref
        kwargs["pk"] = pk
        log(kwargs)

        obj = super().__new__(cls)

        for k in cls.autoattr:
            setattr(obj, k, None)

        for k, v in kwargs.items():
            setattr(obj, k, v)

        return obj

    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    @classmethod
    def table(cls):
        if not hasattr(cls, "_table"):
            ref = db.reference(os.getenv("APP_NAME"))
            cls._table = ref.child(cls.__name__.lower())
        return cls._table

    def _serialize(self, val):
        if val.__class__.__name__ in AutoModel._auto_models:
            # log(val.autoattributes)
            val.save()
            val = {"pk": val.pk, "automodel": val.__class__.__name__}
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = self._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = self._serialize(v)
        return val

    def save(self):
        # filter invalid attributes and other models and save them
        save_data = json.dumps(self, cls=AutoEncoder)

        # update existing record
        if self._ref:
            self._ref.set(save_data)
        # save new record
        else:
            self._ref = self.table().push(value=save_data)
            self._ref.update({"pk": self._ref.key})

        # set key
        self.pk = self._ref.key
        return self.pk

    def delete(self):
        return self._ref.delete()

    @classmethod
    def get(cls, id):
        ref = cls.table().child(str(id))
        if data := ref.get():
            data = AutoEncoder.deserialize(data)
            data["pk"] = ref.key
            data["_ref"] = ref
            obj = cls(**data)
            return obj

    @classmethod
    def all(cls):
        data = cls.table().get()
        objs = []
        if data:
            for k, v in data.items():
                v["pk"] = k
                objs.append(cls(**v))
        return objs

    @classmethod
    def search(cls, **kwargs):
        objs = []
        for k, v in kwargs.items():
            objs += cls.table().order_by_child(k).equal_to(v).get()
        log(objs)
        return [cls(**o) for o in objs]

    @classmethod
    def clear_table(cls):
        cls.table().delete()


AutoModel._auto_models[AutoModel.__name__] = AutoModel
