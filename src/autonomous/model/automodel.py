import importlib
import os
import urllib.parse
from datetime import datetime

import bson
from bson import ObjectId
from mongoengine import Document, connect
from mongoengine.errors import DoesNotExist, ValidationError
from mongoengine.fields import DateTimeField

from autonomous import log

from .autoattr import ListAttr

host = os.getenv("DB_HOST", "db")
port = os.getenv("DB_PORT", 27017)
password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
dbname = os.getenv("DB_DB")
# log(f"Connecting to MongoDB at {host}:{port} with {username}:{password} for {dbname}")
db = connect(
    host=f"mongodb://{username}:{password}@{host}:{port}/{dbname}?authSource=admin"
)
# log(f"{db}")


class AutoModel(Document):
    meta = {"abstract": True}
    last_updated = DateTimeField(default=datetime.now)
    _db = db

    def __init__(self, *args, **kwargs):
        if kwargs.get("pk") or kwargs.get("id"):
            record = self._get_collection().find_one(
                {"_id": kwargs.get("pk") or kwargs.get("id")}
            )
            record["id"] = record.pop("_id")
            kwargs.update(record)
            # log(f"Record: {record}", vars(self), kwargs)
        super().__init__(*args, **kwargs)
        self.last_updated = datetime.now()
        for field_name, field in self._fields.items():
            value = getattr(self, field_name, None)
            # log(f"Field Name: {field_name}, Field: {field} Value: {value}")
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
    def get_schema(cls):
        schema = {}
        for field_name, field in cls._fields.items():
            field_info = {"type": type(field).__name__, "required": field.required}

            # Handle ListField case
            if isinstance(field, ListAttr):
                field_info["item_type"] = type(field.field).__name__

            schema[field_name] = field_info

        return schema

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

        if isinstance(pk, str):
            pk = ObjectId(pk)
        elif isinstance(pk, dict) and "$oid" in pk:
            pk = ObjectId(pk["$oid"])
        log(cls, pk)
        try:
            return cls.objects.get(id=pk)
        except (cls.DoesNotExist, ValidationError):
            print(f"Model {cls.__name__} with pk {pk} not found.")
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
        log(cls.objects._has_data())
        return cls.objects.all()

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
