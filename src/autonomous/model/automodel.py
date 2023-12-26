# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import copy
import importlib
import json
import uuid
from abc import ABC
from datetime import datetime

from autonomous import log
from autonomous.errors import DanglingReferenceError

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
        #### DO NOT TO ANY LOGGING IN THIS METHOD; IT CAUSES INFINITE RECURSION ####
        if not object.__getattribute__(self, "_delayed_obj"):
            _pk = object.__getattribute__(self, "_delayed_pk")
            _model = object.__getattribute__(self, "_delayed_model")
            _obj = _model.get(_pk)
            if not _pk or not _model or _obj is None:
                raise DanglingReferenceError(_model, _pk, _obj)
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
        result = repr(self._instance())
        msg = f"\n<<DelayedModel {self._delayed_model.__name__}:{self._delayed_pk}>>:\t{result}"
        return msg

    def __hash__(self):
        return hash(self._instance())


class AutoModel(ABC):
    attributes = {}
    _table_name = ""
    _table = None
    _orm = ORM

    _save_memo = {}

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
        pk = kwargs.get("pk", args[0] if args else None)
        # set default attributes
        # Get model data from database
        result = cls.table().get(pk) or {}
        # set object attributes
        for k, v in cls.attributes.items():
            if isinstance(v, AutoAttribute):
                v = v.default
            v = copy.deepcopy(v)
            setattr(obj, k, result.get(k, v))

        # update model with keyword arguments
        obj.__dict__ |= kwargs

        # log(obj, kwargs)
        _automodel = obj.__dict__.pop("_automodel", None)
        obj.__dict__ |= cls._deserialize(obj.__dict__)
        obj.__dict__["_automodel"] = _automodel

        obj.last_updated = datetime.now()

        return obj

    def __getattribute__(self, name):
        obj = super().__getattribute__(name)
        if isinstance(obj, DelayedModel):
            self.__dict__[name] = obj._instance()
            return self.__dict__[name]
        return obj

    def __repr__(self) -> str:
        """
        Return a string representation of the AutoModel instance.

        Returns:
            str: A string representation of the AutoModel instance.
        """
        return f"{self.__dict__}"

    def __eq__(self, other):
        return self.pk == other.pk

    def get_save_key(self):
        return f"{self.__class__.__name__}-{self.pk}"

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

    ## TODO: Save all sub objects
    ## FIXME: This is causing issues
    # def _subobj_save(self, obj, key):
    #     if isinstance(obj, list):
    #         for v in obj:
    #             if self._subobj_save(v, key) is None:
    #                 obj.remove(v)
    #     elif isinstance(obj, dict):
    #         for k, v in obj.items():
    #             if self._subobj_save(v, key) is None:
    #                 obj[k] = None
    #     elif issubclass(obj.__class__, (AutoModel, DelayedModel)):
    #         if not obj.pk:
    #             obj.pk = str(uuid.uuid4())
    #         if obj.pk not in self._save_memo[key]:
    #             obj._save(key)

    def _save(self, key):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.

        ALGO:
        - add self.pk to save_memo is self.pk
        - save object not in save memo or without pk into database
        """

        assert self.pk  # sanity check
        assert key and key in AutoModel._save_memo  # sanity check

        local_key = self.get_save_key()

        # if key == local_key:
        #     log(f"Saving root object {key}")
        # else:
        #     log(f"Saving child object {local_key} for root {key}")

        if local_key not in AutoModel._save_memo[key]:
            AutoModel._save_memo[key].append(local_key)
            serialized_obj = self.serialize()
            # log(serialized_obj)
            self.pk = self.table().save(serialized_obj)
        # FIXME: STILL NOT WORKING
        # for attr in self.attributes:
        #     self._subobj_save(getattr(self, attr), key)
        return self.pk

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        if not self.pk:
            self.pk = str(uuid.uuid4())
        key = self.get_save_key()
        AutoModel._save_memo[key] = []
        result = self._save(key)
        assert result == self.pk
        AutoModel._save_memo.pop(key)
        return result

    @classmethod
    def get(cls, pk):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        # breakpoint()
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

    def _subobj_delete(self, obj):
        if isinstance(obj, list):
            for v in obj:
                self._subobj_delete(v)
        elif isinstance(obj, dict):
            for v in obj.values():
                self._subobj_delete(v)
        elif issubclass(obj.__class__, (AutoModel, DelayedModel)):
            obj.delete()

    def delete(self, sub_objects=False):
        """
        Delete this model from the database.
        """
        if sub_objects:
            for k in self.attributes:
                if attr := getattr(self, k):
                    self._subobj_delete(attr)
        return self.table().delete(pk=self.pk)

    serialized_tracker = []

    @classmethod
    def _serialize(cls, val):
        # log(val, type(val))
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
        elif issubclass(val.__class__, (AutoModel, DelayedModel)):
            if val.pk:
                new_val = {
                    "pk": val.pk,
                    "_automodel": val.model_name(),
                }
                # log(new_val)
                # breakpoint()
            else:
                log(
                    val.__class__.__name__,
                    "The above object was not been saved. You must save subobjects if you want them to persist.",
                )
                new_val = None
            val = new_val
        # log(val, type(val))
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
                    # log(val.get("pk"))
                    assert len(val.get("pk"))
                    val = DelayedModel(val["_automodel"], val["pk"])
                else:
                    # log(val.get("pk"))
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
