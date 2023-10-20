# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import copy
import pprint
from abc import ABC
from datetime import datetime

from autonomous import log

from .orm import ORM


class DelayedModel:
    def __init__(self, model, pk):
        self._delayed_model = model
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
            if not self._delayed_obj:
                self._delayed_obj = self._delayed_model.get(self._delayed_pk)
            delattr(self._delayed_obj, name)

    def __repr__(self):
        return f"<DelayedModel {self._delayed_model.__name__} {self._delayed_pk}>"


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
        # set default attributes
        cls.attributes["pk"] = None
        cls.attributes["last_updated"] = datetime.now()

        # Get model data from database
        obj.pk = kwargs.pop("pk", None)
        result = cls.table().get(obj.pk) or {}

        # set object attributes
        for k, v in cls.attributes.items():
            # set attribute from db or set to default value
            setattr(obj, k, result.get(k, v))

        # update model with keyword arguments
        obj.__dict__ |= kwargs

        # log(obj, kwargs)
        data = copy.deepcopy(obj.__dict__)
        data.pop("_automodel", None)
        obj.__dict__ |= cls._deserialize(data)

        obj.last_updated = datetime.now()

        return obj

    @classmethod
    def table(cls):
        if not cls._table or cls._table.name != cls.__name__:
            cls._table = cls._orm(cls)
        return cls._table

    @classmethod
    def model_name(cls):
        """
        Get the fully qualified name of this model.

        Returns:
            str: The fully qualified name of this model.
        """
        return f"{cls.__module__}.{cls.__name__}"

    def __repr__(self) -> str:
        """
        Return a string representation of the AutoModel instance.

        Returns:
            str: A string representation of the AutoModel instance.
        """
        return pprint.pformat(self.__dict__, indent=4, width=7, sort_dicts=True)

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        self.last_updated = datetime.now()
        result = self.serialize()
        record = {k: v for k, v in result.items() if k in self.attributes}
        self.pk = self.table().save(record)
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
        if isinstance(pk, str) and pk.isdigit():
            pk = int(pk)

        result = cls.table().get(pk)
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
        self.table().delete(pk=self.pk)

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
        elif issubclass(val.__class__, (AutoModel, DelayedModel)):
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

        result = self._serialize(self.__dict__)
        return result | {
            "_automodel": self.model_name(),
        }

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if "_automodel" in val:
                val = DelayedModel(cls, val["pk"])
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
