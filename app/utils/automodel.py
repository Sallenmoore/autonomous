import os

import firebase_admin
from firebase_admin import credentials, db
from utils import log

cred = credentials.Certificate(os.getenv("FIREBASE_KEY_FILE"))
firebase_admin.initialize_app(cred, {"databaseURL": os.getenv("FIREBASE_URL")})


class AutoModel:
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "table"):
            ref = db.reference(os.getenv("APP_NAME"))
            cls._table = ref.child(cls.__name__.lower())

        obj = super().__new__(cls)

        obj.pk = kwargs.get("pk")
        obj._ref = kwargs.get("_ref")
        if obj._ref:
            obj.pk = obj._ref.key
        elif obj.pk:
            obj._ref = cls._table.child(str(obj.pk))

        if obj._ref:
            for k, v in obj._ref.get().items():
                if k not in kwargs:
                    setattr(obj, k, v)
        return obj

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def save(self):
        save_data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        if self._ref:
            self._ref.set(save_data)
        else:
            self._ref = self._table.push(value=self.__dict__)
        self.pk = self._ref.key

    def delete(self):
        self._ref.delete()

    @classmethod
    def get(cls, id):
        ref = cls._table.child(str(id))
        if data := ref.get():
            data["pk"] = ref.key
            data["_ref"] = ref
            obj = cls(**data)
            return obj

    @classmethod
    def all(cls):
        data = cls._table.get()
        if data:
            objs = []
            for k, v in data.items():
                v["pk"] = k
                objs.append(cls(**v))
            return objs

    @classmethod
    def clear_table(cls):
        cls._table.delete()
