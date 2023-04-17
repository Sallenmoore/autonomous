# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import copy
import pprint
from abc import ABC
from datetime import datetime

from autonomous import log

from .orm import ORM


class AutoModel(ABC):
    _table = None
    attributes = {}

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)

        # set default attributes
        cls.attributes["pk"] = None

        obj.pk = kwargs.pop("pk", None)
        result = cls.table().get(obj.pk) or {}
        for k, v in cls.attributes.items():
            setattr(obj, k, result.get(k, v))
        obj.__dict__ |= kwargs
        # log(obj, kwargs)
        cls._deserialize(obj.__dict__)
        return obj

    @classmethod
    def table(cls):
        if not cls._table:
            cls._table = ORM(table=cls.__name__)
        return cls._table

    @classmethod
    def model_name(cls):
        return f"{cls.__module__}.{cls.__name__}"

    def __repr__(self) -> str:
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def save(self):
        result = self.serialize()
        record = {k: v for k, v in result.items() if k in self.attributes}
        self.pk = self.table().save(record)
        return self.pk

    @classmethod
    def get(cls, pk):
        result = cls.table().get(pk)
        return cls(**result) if result else None

    @classmethod
    def all(cls):
        return [cls(o) for o in cls.table().all()]

    @classmethod
    def search(cls, **kwargs):
        return [cls(**attribs) for attribs in cls.table().search(**kwargs)]

    def delete(self):
        self.table().delete(pk=self.pk)

    @classmethod
    def _serialize(self, val):
        if isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = self._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = self._serialize(v)
        elif isinstance(val, datetime):
            val = {"_datetime": val.isoformat()}
        elif issubclass(val.__class__, AutoModel):
            val.save()
            val = {
                "_pk": val.pk,
                "_automodel": val.model_name(),
            }

        return val

    def serialize(self):
        return self._serialize(copy.deepcopy(self.__dict__))

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if "_automodel" in val:
                for model in AutoModel.__subclasses__():
                    if model.model_name() == val["_automodel"]:
                        val = model.get(val["_pk"])
                        break
                log(val, model)
                # log(val)
            elif "_datetime" in val:
                val = datetime.fromisoformat(val["_datetime"])
            else:
                for k, v in val.items():
                    val[k] = cls._deserialize(v)
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = cls._deserialize(v)
        return val

    @classmethod
    def deserialize(cls, vars):
        return cls(**vars)
