# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import pprint
from abc import ABC

from .orm import ORM


class AutoModel(ABC):
    _table = None
    attributes = []

    def __new__(cls, *args, **kwargs):
        if not cls._table:
            cls._table = ORM(table=cls.__name__)
        obj = super().__new__(cls)

        # set default attributes
        cls.attributes["pk"] = None

        obj.pk = kwargs.pop("pk", None)
        result = cls._table.get(obj.pk) or {}
        for k, v in cls.attributes.items():
            setattr(obj, k, result.get(k, v))
        obj.__dict__ |= kwargs
        cls._deserialize(obj)
        return obj

    def __repr__(self) -> str:
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def save(self):
        result = self.serialize()
        record = {k: v for k, v in result.items() if k in self.attributes}
        self.pk = self._table.save(record)
        return self.pk

    @classmethod
    def get(cls, pk):
        result = cls._table.get(pk)
        return cls(**result) if result else None

    @classmethod
    def all(cls):
        return [cls(o) for o in cls._table.all()]

    @classmethod
    def search(cls, **kwargs):
        return cls._table.search(**kwargs)

    def delete(self):
        self._table.delete(pk=self.pk)

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

    def serialize(self):
        return self._serialize(self.__dict__)

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

    @classmethod
    def deserialize(cls, vars):
        return vars
