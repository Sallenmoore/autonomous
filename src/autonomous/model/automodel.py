import importlib
import os
import urllib.parse
from datetime import datetime

from bson import ObjectId
from mongoengine import Document, connect, signals
from mongoengine.errors import ValidationError
from mongoengine.fields import DateTimeField

from autonomous import log

host = os.getenv("DB_HOST", "db")
port = os.getenv("DB_PORT", 27017)
password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
dbname = os.getenv("DB_DB")
# log(f"Connecting to MongoDB at {host}:{port} with {username}:{password} for {dbname}")
connect(host=f"mongodb://{username}:{password}@{host}:{port}/{dbname}?authSource=admin")
# log(f"{db}")


class AutoModel(Document):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}
    last_updated = DateTimeField(default=datetime.now)

    def __eq__(self, other):
        return self.pk == other.pk if other else False

    @classmethod
    def auto_pre_init(cls, sender, document, **kwargs):
        log(sender, document, kwargs)
        values = kwargs.pop("values", None)
        if pk := values.get("pk") or values.get("id"):
            # Try to load the existing document from the database
            if existing_doc := sender._get_collection().find_one({"_id": ObjectId(pk)}):
                # Update the current instance with the existing data
                existing_doc.pop("_id", None)
                existing_doc.pop("_cls", None)
                log(f"Existing Document: {existing_doc}")
                for k, v in existing_doc.items():
                    if not values.get(k):
                        values[k] = v

    @classmethod
    def auto_post_init(cls, sender, document, **kwargs):
        document.last_updated = datetime.now()
        for field_name, field in document._fields.items():
            if hasattr(field, "clean_references") and getattr(
                document, field_name, None
            ):
                value = getattr(document, field_name)
                if cleaned_values := field.clean_references(value):
                    setattr(document, field_name, cleaned_values)

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
        module_name, model = (
            model.rsplit(".", 1) if "." in model else (f"models.{model.lower()}", model)
        )
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
        try:
            return cls.objects.get(id=pk)
        except (cls.DoesNotExist, ValidationError):
            log(f"Model {cls.__name__} with pk {pk} not found.")
            return None
        except Exception as e:
            log(f"Error getting model {cls.__name__} with pk {pk}: {e}", _print=True)
            raise e

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
        # log(self.to_json())
        obj = super().save()
        self.pk = obj.pk
        return self.pk

    def delete(self):
        """
        Delete this model from the database.
        """
        return super().delete()


signals.pre_init.connect(AutoModel.auto_pre_init)
signals.post_init.connect(AutoModel.auto_post_init)
