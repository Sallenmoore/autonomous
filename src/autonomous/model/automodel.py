# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import copy
import importlib
import json
from abc import ABC
from datetime import datetime

from autonomous import log
from autonomous.errors import DanglingReferenceError

from .autoattribute import AutoAttribute
from .orm import ORM
from .serializer import AutoDecoder, AutoEncoder


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
        pk = kwargs.pop("pk", None)
        # set default attributes
        # Get model data from database
        result = cls.table().get(pk) or {}

        # set object attributes
        for k, v in cls.attributes.items():
            if isinstance(v, AutoAttribute):
                v = v.default
            setattr(obj, k, result.get(k, copy.deepcopy(v)))
        obj.pk = pk
        obj.__dict__ |= kwargs
        # breakpoint()
        obj.__dict__ = AutoDecoder.decode(obj.__dict__)
        obj._automodel = obj.model_name()
        obj.last_updated = datetime.now()

        return obj

    def __getattribute__(self, name):
        obj = super().__getattribute__(name)
        if isinstance(obj, DelayedModel):
            try:
                self.__dict__[name] = obj._instance()
            except DanglingReferenceError as e:
                log(self.__dict__[name], e)
                raise e
            return self.__dict__[name]
        if isinstance(obj, DelayedModel):
            return obj._instance()
        return obj

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        """
        Return a string representation of the AutoModel instance.

        Returns:
            str: A string representation of the AutoModel instance.
        """
        return json.dumps(self.serialize(), indent=4)

    def __eq__(self, other):
        return self.pk == other.pk

    @classmethod
    def table(cls):
        # breakpoint()
        if not cls._table or cls._table.name != cls.__name__:
            cls.attributes["pk"] = None
            cls.attributes["last_updated"] = datetime.now()
            cls.attributes["_automodel"] = AutoAttribute(
                "TEXT", default=cls.model_name()
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

    @property
    def _id(self):
        """
        Get the primary key of this model.

        Returns:
            int: The primary key of this model.
        """
        return self.pk

    @_id.setter
    def _id(self, _id):
        """
        Get the primary key of this model.

        Returns:
            int: The primary key of this model.
        """
        self.pk = str(_id)

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        serialized_obj = self.serialize()
        serialized_obj["pk"] = self.pk
        self.pk = self.table().save(serialized_obj)

        return self.pk

    @classmethod
    def get(cls, pk):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        table = cls.table()
        result = table.get(pk)
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
        # breakpoint()
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
        for k, v in kwargs.items():
            kwargs[k] = AutoEncoder.encode(v)
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
        return self.table().delete(self.pk)

    def serialize(self):
        """
        Serialize this model to a dictionary.

        Returns:
            dict: A dictionary representation of the serialized model.
        """
        vars = {k: v for k, v in self.__dict__.items() if k in self.attributes}
        json_vars = AutoEncoder.encode(vars)
        return json_vars
