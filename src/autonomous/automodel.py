# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import pprint
from abc import ABC

import redis_om


class AutoModel(redis_om.JsonModel, ABC):
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for k, v in obj.__dict__.items():
            setattr(obj, k, cls._deserialize(v))
        return obj

    def save(self):
        for k, v in self.__dict__.items():
            setattr(self, k, self._serialize(v))
        super().save()
        return self.pk

    @classmethod
    def get(cls, pk):
        try:
            return super().get(pk)
        except redis_om.model.model.NotFoundError as e:
            return None

    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

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

    def delete(self):
        super().delete(self.pk)

    @classmethod
    def all(cls):
        return cls.all_pks()
