from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

import bson
from pymongo import errors as pymongo_errors

from autonomous.db import Document, connect, db_sync, signals
from autonomous.db.errors import ValidationError
from autonomous.db.fields import DateTimeField

from autonomous import log

if TYPE_CHECKING:
    PrimaryKey = bson.ObjectId | str | dict | int | None


_connected: bool = False


def connect_from_env(**overrides) -> str:
    """Open the default MongoDB connection using env vars.

    Reads ``DB_HOST`` / ``DB_PORT`` / ``DB_USERNAME`` / ``DB_PASSWORD`` /
    ``DB_DB`` and calls ``autonomous.db.connect``. Idempotent: subsequent
    calls are no-ops. Returns the URI that was passed to ``connect``.

    Any of the settings may be overridden via keyword args (``host``,
    ``port``, ``username``, ``password``, ``db``) for tests or alternate
    deployments.
    """
    global _connected
    host = overrides.get("host", os.getenv("DB_HOST", "db"))
    port = overrides.get("port", os.getenv("DB_PORT", 27017))
    password = urllib.parse.quote_plus(
        str(overrides.get("password", os.getenv("DB_PASSWORD")))
    )
    username = urllib.parse.quote_plus(
        str(overrides.get("username", os.getenv("DB_USERNAME")))
    )
    dbname = overrides.get("db", os.getenv("DB_DB"))
    uri = f"mongodb://{username}:{password}@{host}:{port}/{dbname}?authSource=admin"
    connect(host=uri)
    _connected = True
    return uri


def _ensure_connected() -> None:
    """Auto-connect on first ORM operation if the consumer hasn't yet.

    Keeps the zero-configuration ergonomics the container-app pattern relies
    on (env vars are already set) without running MongoDB I/O at import time.
    Consumers that want explicit control should call ``connect_from_env`` (or
    ``autonomous.db.connect`` directly) at startup.
    """
    if _connected:
        return
    connect_from_env()


class AutoModel(Document):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}
    last_updated = DateTimeField(default=datetime.now)

    def __eq__(self, other):
        return str(self.pk) == str(other.pk) if other else False

    def __lt__(self, other):
        return str(self.pk) < str(other.pk) if other else False

    def __gt__(self, other):
        return not (str(self.pk) < str(other.pk)) if other else False

    def __le__(self, other):
        return self < other or self == other

    def __ge__(self, other):
        return self > other or self == other

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(
            (
                self.model_name(),
                self.pk,
            )
        )

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

    @property
    def path(self) -> str:
        return f"{self.model_name().lower()}/{self.pk}"

    def model_name(self, qualified: bool = False) -> str:
        """Return the model's class name (or the qualified ``module.Class``)."""
        return (
            f"{self.__module__}.{self._class_name}" if qualified else self._class_name
        )

    @classmethod
    def get_model(
        cls, model: str | type[AutoModel], pk: PrimaryKey = None
    ) -> AutoModel | type[AutoModel] | None:
        """Look up a registered ``AutoModel`` subclass by name (or pass-through).

        With ``pk`` supplied, fetches and returns the instance. Otherwise
        returns the class itself.
        """
        try:
            Model = cls.load_model(model)
        except ValueError:
            Model = None
        return Model.get(pk) if Model and pk else Model

    @classmethod
    def load_model(cls, model: str | type[AutoModel]) -> type[AutoModel]:
        """Resolve ``model`` (string name or class) to an ``AutoModel`` subclass."""
        if not isinstance(model, str):
            return model

        subclasses = AutoModel.__subclasses__()
        visited_subclasses: list[type[AutoModel]] = []
        while subclasses:
            subclass = subclasses.pop()
            if "_meta" in subclass.__dict__ and not subclass._meta.get("abstract"):
                if subclass.__name__.lower() == model.lower():
                    return subclass
            if subclass not in visited_subclasses:
                subclasses += subclass.__subclasses__()
                visited_subclasses += [subclass]
        raise ValueError(f"Model {model} not found")

    @classmethod
    def get(cls, pk: PrimaryKey) -> Self | None:
        """Get a single model instance by primary key.

        Returns ``None`` if the document doesn't exist or ``pk`` can't be
        coerced to a valid ``ObjectId``. Re-raises pymongo
        ``OperationFailure`` / ``ConnectionFailure`` so DB outages don't
        get silently swallowed.
        """
        _ensure_connected()

        if isinstance(pk, str):
            try:
                pk = bson.ObjectId(pk)
            except bson.errors.InvalidId:
                return None
        elif isinstance(pk, dict) and "$oid" in pk:
            pk = bson.ObjectId(pk["$oid"])
        try:
            result = cls.objects.get(id=pk)
        except cls.DoesNotExist:
            return None
        except ValidationError as e:
            log(f"Model Validation failure {cls.__name__} [{pk}]: {e}")
            return None
        except (pymongo_errors.OperationFailure, pymongo_errors.ConnectionFailure) as e:
            log(
                f"DB error getting model {cls.__name__} with pk {pk}: {e}",
                _print=True,
            )
            raise
        else:
            return result

    @classmethod
    def random(cls) -> Self | None:
        """Return a single random instance of this model, or ``None`` if empty."""
        _ensure_connected()
        pipeline = [{"$sample": {"size": 1}}]

        result = cls.objects.aggregate(pipeline)
        random_document = next(result, None)
        return cls._from_son(random_document) if random_document else None

    @classmethod
    def all(cls) -> list[Self]:
        """Return every instance of this model. Use ``search`` for filtering."""
        _ensure_connected()
        return list(cls.objects())

    @classmethod
    def search(
        cls,
        _order_by: tuple[str, ...] | list[str] | None = None,
        _limit: int | list[int] | None = None,
        **kwargs: Any,
    ) -> list[Self]:
        """Case-insensitive substring search across the supplied fields.

        String values become ``__icontains`` queries; non-string values
        become exact matches. ``_order_by`` is forwarded to mongoengine;
        ``_limit`` accepts either a slice end or a ``[start, end]`` pair.
        """
        _ensure_connected()
        new_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                new_kwargs[f"{k}__icontains"] = v
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
    def find(cls, **kwargs: Any) -> Self | None:
        """Return the first instance matching ``**kwargs``, or ``None``."""
        _ensure_connected()
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

    def save(self, sync: bool = False) -> Any:
        """Persist this document and return its primary key.

        With ``sync=True`` the new ``pk`` is also enqueued for vector
        re-indexing via ``autonomous.db.db_sync``.
        """
        _ensure_connected()
        super().save()

        if sync:
            db_sync.request_indexing(
                self.pk, collection_name=self._get_collection_name()
            )

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

    def delete(self) -> None:
        """Delete this document from the database."""
        _ensure_connected()
        return super().delete()


signals.pre_init.connect(AutoModel._auto_pre_init)
signals.post_init.connect(AutoModel._auto_post_init)
signals.pre_save.connect(AutoModel._auto_pre_save)
signals.post_save.connect(AutoModel._auto_post_save)
