import importlib
import os
import urllib.parse
from datetime import datetime

import bson

from autonomous import log
from autonomous.db import Document, connect, signals
from autonomous.db.errors import ValidationError
from autonomous.db.fields import DateTimeField

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
        values = kwargs.pop("values", None)
        if pk := values.get("pk") or values.get("id"):
            # Try to load the existing document from the database
            if existing_doc := sender._get_collection().find_one(
                {"_id": bson.ObjectId(pk)}
            ):
                # Update the current instance with the existing data
                existing_doc.pop("_id", None)
                existing_doc.pop("_cls", None)
                for k, v in existing_doc.items():
                    if not values.get(k):
                        values[k] = v

    @classmethod
    def _auto_pre_init(cls, sender, document, **kwargs):
        sender.auto_pre_init(sender, document, **kwargs)

    @classmethod
    def auto_post_init(cls, sender, document, **kwargs):
        document.last_updated = datetime.now()

    @classmethod
    def _auto_post_init(cls, sender, document, **kwargs):
        sender.auto_post_init(sender, document, **kwargs)

    def model_name(self, qualified=False):
        """
        Get the fully qualified name of this model.

        Returns:
            str: The fully qualified name of this model.
        """
        return (
            f"{self.__module__}.{self._class_name}" if qualified else self._class_name
        )

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
            try:
                pk = bson.ObjectId(pk)
            except bson.errors.InvalidId:
                return None
        elif isinstance(pk, dict) and "$oid" in pk:
            pk = bson.ObjectId(pk["$oid"])
        try:
            return cls.objects.get(id=pk)
        except cls.DoesNotExist as e:
            log(f"Model {cls.__name__} with pk {pk} not found : {e}")
            return None
        except ValidationError as e:
            log(f"Model Validation failure {cls.__name__} [{pk}]: {e}")
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
        new_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                new_k = f"{k}__icontains"
                new_kwargs[new_k] = v
            else:
                new_kwargs[k] = v
        results = cls.objects(**new_kwargs)
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

    @classmethod
    def auto_pre_save(cls, sender, document, **kwargs):
        """
        Post-save hook for this model.
        """
        pass

    @classmethod
    def _auto_pre_save(cls, sender, document, **kwargs):
        """
        Post-save hook for this model.
        """
        sender.auto_pre_save(sender, document, **kwargs)

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

    @classmethod
    def auto_post_save(cls, sender, document, **kwargs):
        """
        Post-save hook for this model.
        """
        pass

    @classmethod
    def _auto_post_save(cls, sender, document, **kwargs):
        """
        Post-save hook for this model.
        """
        sender.auto_post_save(sender, document, **kwargs)

    def delete(self):
        """
        Delete this model from the database.
        """
        return super().delete()


signals.pre_init.connect(AutoModel._auto_pre_init)
signals.post_init.connect(AutoModel._auto_post_init)
signals.pre_save.connect(AutoModel._auto_pre_save)
signals.post_save.connect(AutoModel._auto_post_save)
