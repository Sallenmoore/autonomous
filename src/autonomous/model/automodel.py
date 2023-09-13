# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for default values
import copy
import pprint
from abc import ABC
from datetime import datetime

from autonomous import log

from .orm import ORM


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
        # log(f"Creating {cls.__name__}")
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
        return cls.table().find(**kwargs)

    def delete(self):
        """
        Delete this model from the database.
        """
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
        """
        Serialize this model to a dictionary.

        Returns:
            dict: A dictionary representation of the serialized model.
        """
        return self._serialize(copy.deepcopy(self.__dict__))

    @classmethod
    def _deserialize(cls, val):
        if isinstance(val, dict):
            if "_automodel" in val:
                for model in AutoModel.__subclasses__():
                    if model.model_name() == val["_automodel"]:
                        val = model.get(val["_pk"])
                        break
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
        return cls(**vars)
