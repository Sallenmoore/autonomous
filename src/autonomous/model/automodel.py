import importlib
import os
import urllib.parse
from datetime import datetime

from bson import ObjectId
from mongoengine import Document, connect
from mongoengine.fields import DateTimeField

from autonomous import log

from .autoattr import DictAttr, ListAttr

host = os.getenv("DB_HOST", "db")
port = os.getenv("DB_PORT", 27017)
password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
db = os.getenv("DB_DB")
db = connect(host=f"mongodb://{username}:{password}@{host}:{port}")


class AutoModel(Document):
    meta = {"abstract": True, "allow_inheritance": True}
    last_updated = DateTimeField(default=datetime.now)
    _db = db

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.pop("pk", None):
            self.reload()
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.last_updated = datetime.now()

        for field_name, field in self._fields.items():
            value = getattr(self, field_name, None)
            # log(
            #     f"Field: {field_name}, Type:{type(value)}, Value: {value}, {hasattr(field, "clean_references")}"
            # )

            if hasattr(field, "clean_references") and value:
                cleaned_values, updated = field.clean_references(value)
                # log(f"Cleaned Values: {cleaned_values}")
                if updated:
                    setattr(self, field_name, cleaned_values)

    def __eq__(self, other):
        return self.pk == other.pk if other else False

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

    @classmethod
    def get(cls, pk):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        if pk and isinstance(pk, str):
            pk = ObjectId(pk)
        try:
            return cls.objects(pk=pk).get()
        except Exception as e:
            log(e)
            return None

    @classmethod
    def random(cls):
        """
        Get a model by primary key.

        Args:
            pk (int): The primary key of the model to retrieve.

        Returns:
            AutoModel or None: The retrieved AutoModel instance, or None if not found.
        """
        pipeline = [{"$sample": {"size": 1}}]

        result = cls.objects.aggregate(pipeline)
        random_document = next(result, None)
        return cls._from_son(random_document) if random_document else None

    @classmethod
    def all(cls):
        """
        Get all models of this type.

        Returns:
            list: A list of AutoModel instances.
        """
        return list(cls.objects())

    @classmethod
    def search(cls, _order_by=None, _limit=None, **kwargs):
        """
        Search for models containing the keyword values.

        Args:
            **kwargs: Keyword arguments to search for (dict).

        Returns:
            list: A list of AutoModel instances that match the search criteria.
        """
        results = cls.objects(**kwargs)
        if _order_by:
            results = results.order_by(*_order_by)
        if _limit:
            if isinstance(_limit, list):
                results = results[_limit[0] : _limit[-1]]
            else:
                results = results[:_limit]
        return list(results)

    @classmethod
    def find(cls, **kwargs):
        """
        Find the first model containing the keyword values and return it.

        Args:
            **kwargs: Keyword arguments to search for (dict).

        Returns:
            AutoModel or None: The first matching AutoModel instance, or None if not found.
        """
        return cls.objects(**kwargs).first()

    def save(self):
        """
        Save this model to the database.

        Returns:
            int: The primary key (pk) of the saved model.
        """
        # log(self.model_dump_json())
        return super().save()

    def delete(self):
        """
        Delete this model from the database.
        """
        return super().delete()
