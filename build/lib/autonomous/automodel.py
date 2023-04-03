# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import pprint
from abc import ABC

from .db import db as _database


class AutoModel(ABC):
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for k, v in obj.__dict__.items():
            setattr(obj, k, cls._deserialize(v))
        return obj

    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def save(self):
        for k, v in self.__dict__.items():
            setattr(self, k, self._serialize(v))
        _database.save(table=self.__class__.__name__, model=self)
        return self.pk

    @classmethod
    def get(cls, pk):
        return _database.get(table=cls.__name__, pk=pk)

    @classmethod
    def all(cls):
        return cls.all_pks()

    @classmethod
    def search(cls, **kwargs):
        return cls.search(table=cls.__name__, **kwargs)

    def delete(self):
        _database.delete(table=self.__class__.__name__, pk=self.pk)

    @classmethod
    def _serialize(self, val):
        if isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = self._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = self._serialize(v)
        elif issubclass(val.__class__, AutoModel):
            val.save()
            val = {"_pk": val.pk, "_automodel": val.__class__.__name__}

        return val

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if "_automodel" in val:
                autoclass = filter(
                    lambda klass: val["_automodel"]
                    == klass.__name__.rsplit(".", 1)[-1],
                    AutoModel.__subclasses__(),
                )
                model = next(autoclass)
                # breakpoint()
                val = model.get(val["_pk"])
            else:
                for k, v in val.items():
                    val[k] = cls._deserialize(v)
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = cls._deserialize(v)
        return val
