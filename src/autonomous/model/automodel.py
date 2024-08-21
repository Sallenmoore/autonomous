# PYDANTIC NOTES: https://pydantic-docs.helpmanual.io/usage/models/
# opt : Optional[str]  # for optional attributes
# default : Optional[str] = "value"  # for optional default values
# #from typing import ClassVar
import abc
import importlib
import json
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from autonomous import log

from .orm import ORM


class AutoModel(BaseModel, abc.ABC):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
    pk: str = Field(default=None)
    last_updated: datetime = Field(default_factory=lambda: datetime.now())
    table_name: ClassVar[str] = ""

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if not name.startswith("_") and name in dict(self):
            # log(f"Deserializing {name}, attr: {attr}")
            attr = self._deserialize(name, attr)
        return attr

    def __setattr__(self, name, value):
        value = self._serialize(name, value)
        super().__setattr__(name, value)

    def __eq__(self, other):
        return self.pk == other.pk

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
        for key, val in list(kwargs.items()):
            if (
                getattr(cls, key, None)
                and getattr(cls, key).fset
                and f"_{key}" in cls.attributes
            ):
                kwargs[f"_{key}"] = kwargs.pop(key)
        obj.__dict__ |= kwargs
        # breakpoint()
        obj.__dict__ = AutoDecoder.decode(obj.__dict__)
        obj._automodel = obj.model_name(qualified=True)
        obj.last_updated = datetime.now()
        return obj

    def __getattribute__(self, name):
        obj = super().__getattribute__(name)
        if not name.startswith("__"):
            if isinstance(obj, DelayedModel):
                try:
                    result = obj._instance()
                except DanglingReferenceError as e:
                    log(e)
                    super().__setattr__(name, None)
                    return None
                else:
                    super().__setattr__(name, result)

            elif isinstance(obj, list):
                results = []
                scrubbed = False
                for i, item in enumerate(obj):
                    if isinstance(item, DelayedModel):
                        try:
                            result = item._instance()
                        except DanglingReferenceError as e:
                            log(e)
                            scrubbed = True
                        else:
                            results.append(result)
                if scrubbed:
                    super().__setattr__(name, results)
                    obj = results

            elif isinstance(obj, dict):
                results = {}
                scrubbed = False
                for key, item in obj.items():
                    if isinstance(item, DelayedModel):
                        try:
                            result = item._instance()
                        except DanglingReferenceError as e:
                            log(e)
                            scrubbed = True
                        else:
                            results[key] = result
                    if scrubbed:
                        super().__setattr__(name, results)
                        obj = results
        return obj

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        """
        Return a string representation of the AutoModel instance.

        Returns:
            str: A string representation of the AutoModel instance.
        """
        return str(self.__dict__)

    def __eq__(self, other):
        return self.pk == other.pk if other else False

    @classmethod
    def load_model(cls, model, module=None):
        if not module:
            module = f"models.{model.lower()}"
        module = importlib.import_module(module)
        return getattr(module, model)

    @classmethod
    def table(cls):
        table_name = cls.table_name or cls.__name__.lower()
        # log(f"Table Name: {table_name}")
        return ORM(table_name, cls.model_fields)

    @classmethod
    def model_name(cls, qualified=False):
        """
        Get the fully qualified name of this model.

        Returns:
            str: The fully qualified name of this model.
        """
        return f"{cls.__module__}.{cls.__name__}" if qualified else cls.__name__

    @classmethod
    def load_model(cls, model):
        module_name, model = model.rsplit(".", 1) if "." in model else ("models", model)
        module = importlib.import_module(module_name)
        return getattr(module, model)

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        # log(self.model_dump_json())
        record = json.loads(self.model_dump_json())
        for k, v in record.items():
            record[k] = self._serialize(k, v)
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
        result = cls.table().get(pk)
        log(result)
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
        results = cls.table().all()
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
            kwargs[k] = v
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
        for k, v in kwargs.items():
            kwargs[k] = v
        attribs = cls.table().find(**kwargs)
        return cls(**attribs) if attribs else None

    def update(self, values):
        """
        Delete this model from the database.
        """
        if not isinstance(values, dict):
            raise ValueError("Values must be a dictionary")
        for k, v in values.items():
            if k in self.attributes or f"_{k}" in self.attributes:
                if getattr(self.__class__, k, None) and getattr(self.__class__, k).fset:
                    getattr(self.__class__, k).fset(self, v)
                elif k in self.attributes:
                    setattr(self, k, v)
        self.save()

    def delete(self):
        """
        Delete this model from the database.
        """
        return self.table().delete(self.pk)
