# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values

import importlib
import os
from abc import ABC
from datetime import datetime

import redis
from redis_om import Field as AutoField  # wraps the redis-om Field type
from redis_om import JsonModel, Migrator

from autonomous import log


class DelayedModel:
    def __init__(self, model, pk):
        module_name, class_name = model.rsplit(".", 1)
        module = importlib.import_module(module_name)
        self._delayed_model = getattr(module, class_name)
        self._delayed_pk = pk
        self._delayed_obj = None

    def _create_instance(self):
        if self._delayed_obj is None:
            self._delayed_obj = self._delayed_model.get(self._delayed_pk)

    def __getattribute__(self, name):
        if name in [
            "_delayed_model",
            "_delayed_pk",
            "_delayed_obj",
            "_create_instance",
        ]:
            return object.__getattribute__(self, name)
        self._create_instance()
        return getattr(self._delayed_obj, name)

    def __getattr__(self, attr):
        self._create_instance()
        return getattr(self._delayed_obj, attr)

    def __setattr__(self, name, value):
        if name in ["_delayed_model", "_delayed_pk", "_delayed_obj"]:
            object.__setattr__(self, name, value)
        else:
            self._create_instance()
            setattr(self._delayed_obj, name, value)

    def __delattr__(self, name):
        if name in ["_delayed_model", "_delayed_pk", "_delayed_obj"]:
            object.__delattr__(self, name)
        else:
            self._create_instance()
            delattr(self._delayed_obj, name)

    def __repr__(self):
        return f"<DelayedModel {self._delayed_model.__name__} {self._delayed_pk}>"


class AutoModel(JsonModel, ABC):
    class Meta:
        database = redis.Redis(
            port=os.getenv("REDIS_PORT", 6379),
            host=os.getenv("REDIS_HOST", "redis"),
            password=os.getenv("REDIS_PASSWORD"),
            username=os.getenv("REDIS_USERNAME"),
            db=int(os.getenv("REDIS_DB", 0)),
        )

    def __new__(cls, *args, **kwargs):
        """
        Create a new instance of the AutoModel.

        This method is responsible for creating a new instance of the AutoModel class.
        It sets default attributes, populates the object from the database if a primary key is provided,
        and handles additional keyword arguments.

        Args:
            cls: The class itself.
            *args: Positional arguments.
            **kwargs: Keyword arguments, including 'pk' for primary key.

        Returns:
            obj: The created AutoModel instance.
        """
        # cls.Meta.model_key_prefix = cls.__name__

        obj = super().__new__(cls)
        obj.deserialize()
        return obj

    @classmethod
    def model_name(cls):
        """
        Get the fully qualified name of this model.

        Returns:
            str: The fully qualified name of this model.
        """
        return f"{cls.__module__}.{cls.__name__}"

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        for val in self.__dict__:
            if issubclass(val.__class__, (AutoModel, DelayedModel)):
                val.save()
        self.last_updated = datetime.now()
        self.serialize()
        return super().save()

    def delete(self):
        return super().delete(self.pk)

    @classmethod
    def all(cls):
        Migrator().run()
        return super().find().all()

    @classmethod
    def get(cls, pk):
        try:
            return super().get(pk)
        except Exception as e:
            log(e)
            return None

    @classmethod
    def search(cls, expression):
        Migrator().run()
        return super().find(expression).all()

    @classmethod
    def find(cls, expression):
        results = cls.search(expression)
        return results[0] if results else None

    @classmethod
    def _serialize(cls, val):
        if isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = cls._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = cls._serialize(v)
        elif issubclass(val.__class__, (AutoModel, DelayedModel)):
            val = {"pk": val.pk, "_automodel": val.model_name()}

        return val

    def serialize(self):
        """
        Serialize this model to a dictionary.

        Returns:
            dict: A dictionary representation of the serialized model.
        """
        self._serialize(self.__dict__)
        return self.__dict__

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if "_automodel" in val:
                val = DelayedModel(val.get("_automodel"), val.get("pk"))
            else:
                for k, v in val.items():
                    val[k] = cls._deserialize(v)
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = cls._deserialize(v)
        return val

    def deserialize(self):
        """
        Deserialize a dictionary to a model.

        Args:
            vars (dict): The dictionary to deserialize.

        Returns:
            AutoModel: A deserialized AutoModel instance.
        """
        self._deserialize(self.__dict__)
        return self

    @classmethod
    def flush_table(cls):
        for obj in cls.all():
            obj.delete()
