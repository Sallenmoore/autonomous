# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import importlib
import json
from abc import ABC
from datetime import datetime

from autonomous import log

from .autoattribute import AutoAttribute
from .orm import ORM


class DelayedModel:
    def __init__(self, model, pk):
        # log(model, pk)
        assert model
        assert pk
        module_name, class_name = model.rsplit(".", 1)
        module = importlib.import_module(module_name)
        model = getattr(module, class_name)
        object.__setattr__(self, "_delayed_model", model)
        object.__setattr__(self, "_delayed_pk", pk)
        object.__setattr__(self, "_delayed_obj", None)

    def _instance(self):
        if not object.__getattribute__(self, "_delayed_obj"):
            _pk = object.__getattribute__(self, "_delayed_pk")
            _model = object.__getattribute__(self, "_delayed_model")

            _obj = _model.get(_pk)

            try:
                assert _obj
            except AssertionError as e:
                msg = f"{e}\n\nModel relationship error. Most likely failed to clean up dangling reference.\nModel: {_model}\npk: {_pk}\nResult: {_obj}"
                log(msg)
                raise Exception(msg)
            else:
                object.__setattr__(self, "_delayed_obj", _obj)

        return object.__getattribute__(self, "_delayed_obj")

    # def __getattr__(self, name):
    #     return getattr(self._instance(), name)

    def __getattribute__(self, name):
        # log(name)
        if name in [
            "_delayed_model",
            "_delayed_pk",
            "_delayed_obj",
            "_instance",
        ]:
            return object.__getattribute__(self, name)
        return object.__getattribute__(self._instance(), name)

    def __setattr__(self, name, value):
        if name.startswith("_delayed"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._instance(), name, value)

    def __delattr__(self, name):
        delattr(self._instance(), name)

    def __nonzero__(self):
        return bool(self._instance())

    def __str__(self):
        return str(self._instance())

    def __repr__(self):
        result = repr(self._delayed_obj)
        msg = f"<<DelayedModel {self._delayed_model.__name__}:{self._delayed_pk}>>\n"
        msg += f"{result}\n\n"
        return msg

    def __hash__(self):
        return hash(self._instance())


class AutoModel(ABC):
    attributes = {}
    _table_name = ""
    _table = None
    _orm = ORM

    __save_memo = []

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
        obj = super().__new__(cls)
        # set default attributes
        # Get model data from database
        result = cls.table().get(kwargs.get("pk")) or {}
        # set object attributes
        for k, v in cls.attributes.items():
            # set attribute from db or set to default value
            if isinstance(v, tuple):
                setattr(obj, k, result.get(k, v[0]))
            elif isinstance(v, AutoAttribute):
                setattr(obj, k, result.get(k, v.default))
            else:
                setattr(obj, k, result.get(k, v))

        # update model with keyword arguments
        obj.__dict__ |= kwargs

        # log(obj, kwargs)
        _automodel = obj.__dict__.pop("_automodel", None)
        obj.__dict__ |= cls._deserialize(obj.__dict__)
        obj.__dict__["_automodel"] = _automodel

        obj.last_updated = datetime.now()

        return obj

    def __repr__(self) -> str:
        """
        Return a string representation of the AutoModel instance.

        Returns:
            str: A string representation of the AutoModel instance.
        """
        return f"{self.__dict__}"

    def __getattribute__(self, name):
        obj = super().__getattribute__(name)
        if isinstance(obj, DelayedModel):
            return obj._instance()
        return obj

    @classmethod
    def table(cls):
        # breakpoint()
        if not cls._table or cls._table.name != cls.__name__:
            cls.attributes["pk"] = AutoAttribute("TAG", primary_key=True)
            cls.attributes["last_updated"] = datetime.now()
            cls.attributes["_automodel"] = AutoAttribute(
                "TAG", default=cls.model_name()
            )
            cls._table = cls._orm(cls._table_name or cls.__name__, cls.attributes)
        return cls._table

    @classmethod
    def model_name(cls):
        """
        Get the fully qualified name of this model.

        Returns:
            str: The fully qualified name of this model.
        """
        return f"{cls.__module__}.{cls.__name__}"

    @classmethod
    def _subobj_save(cls, obj):
        if isinstance(obj, list):
            for v in obj:
                cls._subobj_save(v)
        elif isinstance(obj, dict):
            for v in obj.values():
                cls._subobj_save(v)
        elif issubclass(obj.__class__, (AutoModel, DelayedModel)):
            if f"{obj.__class__.__name__}-{obj.pk}" not in AutoModel.__save_memo:
                AutoModel.__save_memo.append(f"{obj.__class__.__name__}-{obj.pk}")
                assert obj._save()

    def _save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        # log(self.pk, AutoModel.__save_memo, self.__class__.__name__)

        # for k in self.attributes:
        #     subobj = getattr(self, k)
        #     self._subobj_save(subobj)

        self.last_updated = datetime.now()
        record = self.serialize()
        # log(type(record), record)
        self.pk = self.table().save(record)
        return self.pk

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        pk = self._save()
        return pk

    @classmethod
    def get(cls, pk):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        if isinstance(pk, str) and pk.isdigit():
            pk = int(pk)

        result = cls.table().get(pk)
        return cls(**result) if result else None

    @classmethod
    def random(cls):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        result = cls.table().random()
        return cls(**result) if result else None

    @classmethod
    def all(cls):
        """
        Get all models of this type.

        Returns:
            list: A list of AutoModel instances.
        """
        return [cls(**o) for o in cls.table().all()]

    @classmethod
    def search(cls, **kwargs):
        """
        Search for models containing the keyword values.

        Args:
            **kwargs: Keyword arguments to search for (dict).

        Returns:
            list: A list of AutoModel instances that match the search criteria.
        """
        return [cls(**attribs) for attribs in cls.table().search(**kwargs)]

    @classmethod
    def find(cls, **kwargs):
        """
        Find the first model containing the keyword values and return it.

        Args:
            **kwargs: Keyword arguments to search for (dict).

        Returns:
            AutoModel or None: The first matching AutoModel instance, or None if not found.
        """
        attribs = cls.table().find(**kwargs)
        return cls(**attribs) if attribs else None

    def delete(self):
        """
        Delete this model from the database.
        """
        return self.table().delete(pk=self.pk)

    serialized_tracker = []

    @classmethod
    def _serialize(cls, val):
        if isinstance(val, list):
            new_list = []
            for v in val:
                obj = cls._serialize(v)
                new_list.append(obj)
            val = new_list
        elif isinstance(val, dict):
            new_dict = {}
            for k, v in val.items():
                new_dict[k] = cls._serialize(v)
            val = new_dict
        elif isinstance(val, datetime):
            val = {"_datetime": val.isoformat()}
        elif issubclass(val.__class__, (AutoModel, DelayedModel)) and val.pk:
            val = {
                "pk": val.pk,
                "_automodel": val.model_name(),
            }

        return val

    def serialize(self):
        """
        Serialize this model to a dictionary.

        Returns:
            dict: A dictionary representation of the serialized model.
        """
        record = {k: v for k, v in self.__dict__.items() if k in self.attributes}
        result = self._serialize(record)
        return result | {
            "_automodel": self.model_name(),
        }

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if val.get("_automodel"):
                if val.get("pk"):
                    # log(val.get('pk'))
                    assert len(val.get("pk"))
                    val = DelayedModel(val["_automodel"], val["pk"])
                else:
                    val = None
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
        """
        Deserialize a dictionary to a model.

        Args:
            vars (dict): The dictionary to deserialize.

        Returns:
            AutoModel: A deserialized AutoModel instance.
        """
        if "_automodel" not in vars:
            raise ValueError("Cannot only deserialize automodel objects")

        return cls(**vars)
