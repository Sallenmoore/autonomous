import os
import pprint

import firebase_admin
from firebase_admin import credentials, db
from utils import log

cred = credentials.Certificate(os.getenv("FIREBASE_KEY_FILE"))
firebase_admin.initialize_app(cred, {"databaseURL": os.getenv("FIREBASE_URL")})


class AutoModel:
    _auto_models = {}

    def __new__(cls, *args, **kwargs):

        obj = super().__new__(cls)

        # get the object references if existing object and update
        obj.pk = kwargs.get("pk")
        obj._ref = kwargs.get("_ref")
        if obj._ref:
            obj.pk = obj._ref.key
        elif obj.pk:
            obj._ref = cls.table().child(str(obj.pk))

        if obj._ref:
            # must pass an object here to keep from getting infinite recursion
            AutoModel.deserialize(obj._ref.get(), obj)

        # deserialize automodels
        # - must pass an object here to keep from getting infinite recursion
        AutoModel.deserialize(kwargs, obj)

        # log(kwargs.get("tasks"))
        obj.__init__(*args, **kwargs)

        return obj

    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def __init__(self, *args, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        _summary_
        _extended_summary_
        """
        AutoModel._auto_models[cls.__name__] = cls

    def save(self):
        # filter invalid attributes and other models and save them
        save_data = self.serialize()

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
        self._ref.delete()

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

    def serialize(self):
        """
        _summary_
        _extended_summary_
        Args:
            val (_type_): _description_
        """
        save_data = {}
        for k, v in self.__dict__.items():
            # log(k, v, type(v))
            if k.startswith("_"):
                continue
            save_data[k] = self._serialize(v)
        return save_data

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict) and "automodel" in val:
            # log(val)
            model = AutoModel._auto_models[val["automodel"]]

            val = model(pk=val["pk"])
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = cls._deserialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = cls._deserialize(v)
        return val

    @classmethod
    def deserialize(cls, data, obj=None):
        if not isinstance(data, dict):
            return data

        if not obj:
            obj = cls()

        for k, v in data.items():
            v = cls._deserialize(v)
            setattr(obj, k, v)
        return obj

    @classmethod
    def get(cls, id):
        ref = cls.table().child(str(id))
        if data := ref.get():
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
