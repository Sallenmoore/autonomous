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

# Cache for AutoModel.load_model() string-name resolution. The tree walk
# over AutoModel.__subclasses__() is O(n) in the registered model count
# and gets called per dispatch in agent code paths — memoizing the
# successful lookups gives ~10-50ms back per call on a deep tree.
# Additive-only: misses (ValueError) are NOT cached, because a subclass
# may be imported later. Tests that want to reset the cache between
# runs should call AutoModel._invalidate_load_model_cache().
_LOAD_MODEL_CACHE: dict[str, type["AutoModel"]] = {}


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


def _maybe_select_related(qs, flag):
    """Apply ``.select_related(max_depth=...)`` to ``qs`` per ``flag``, else
    return ``qs`` unchanged.

    ``flag``: falsy (``False`` / ``0`` / ``None``) → off; ``True`` → depth 1;
    int ``N`` (≥ 1) → depth ``N``. ``bool`` is an ``int`` subclass, so both
    pass the type check; other types raise ``TypeError``; negative ints raise
    ``ValueError``.
    """
    if not flag:                       # False / 0 / None → off
        return qs
    if not isinstance(flag, int):      # bool & int pass; str/float/list rejected
        raise TypeError("_select_related must be a bool or int")
    if flag < 1:                       # negative (truthy) int
        raise ValueError("_select_related must be True or a positive int")
    return qs.select_related(max_depth=int(flag))


class AutoModel(Document):
    meta = {"abstract": True, "allow_inheritance": True, "strict": False}
    last_updated = DateTimeField(default=datetime.now)

    #: Side-load behaviour for ``Model(pk=...)``. When True (the default),
    #: pre-init reads the document from MongoDB and merges any stored
    #: fields the caller didn't pass. Set to False on a subclass that
    #: doesn't want a DB hit per construction.
    auto_load_on_init: bool = True

    def __eq__(self, other):
        if not other or not hasattr(other, "pk"):
            return False
        return str(self.pk) == str(other.pk)

    def __lt__(self, other):
        if not other or not hasattr(other, "pk"):
            return NotImplemented
        return str(self.pk) < str(other.pk)

    def __gt__(self, other):
        if not other or not hasattr(other, "pk"):
            return NotImplemented
        return str(self.pk) > str(other.pk)

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
    def auto_pre_init(cls, sender, document, **kwargs) -> None:
        """Side-load fields from MongoDB on ``Model(pk=...)`` construction.

        When the caller passes only a primary key (``Model(pk=x)`` /
        ``Model(id=x)``), this hook fetches the stored document and fills
        in any field the caller didn't explicitly provide. The caller's
        kwargs always win — useful for partial updates like
        ``Model(pk=x, name="new")`` which becomes equivalent to
        ``Model.get(x); m.name = "new"`` without an extra round trip in
        userland.

        Bypass entirely by setting ``cls.auto_load_on_init = False``.

        Failure modes that are *not* errors:
          - ``created=False`` — the document is being built FROM the
            store (``_from_son`` on the query path, ``reload``, dereference,
            unpickle): ``values`` already *is* the stored document, so the
            fetch re-read it and merged nothing — an N+1 on every query
            materialization (#250). ``from_json`` is the one from-store
            path that still hydrates; see its override below.
          - ``values`` kwarg missing — nothing to merge into; return
          - ``pk`` malformed (not a valid ObjectId) — return
          - document not found in DB — return
          - DB unavailable — return (logged elsewhere)
        """
        if not getattr(sender, "auto_load_on_init", True) or not kwargs.get(
            "created", True
        ):
            return
        values = kwargs.get("values")
        if not values:
            return
        pk = values.get("pk") or values.get("id")
        if not pk:
            return
        try:
            oid = bson.ObjectId(pk)
        except (bson.errors.InvalidId, TypeError):
            return
        try:
            existing_doc = sender._get_collection().find_one({"_id": oid})
        except (
            pymongo_errors.OperationFailure,
            pymongo_errors.ConnectionFailure,
        ) as exc:
            log(f"auto_pre_init DB error for {sender.__name__} pk={pk}: {exc}")
            return
        if not existing_doc:
            return
        existing_doc.pop("_id", None)
        existing_doc.pop("_cls", None)
        # Fix: previously used ``not values.get(k)`` which clobbered
        # legitimate falsy values (0, False, "", []). Compare presence.
        for k, v in existing_doc.items():
            if k not in values:
                values[k] = v

    @classmethod
    def _auto_pre_init(cls, sender, document, **kwargs):
        # The receiver is connected sender-unfiltered, so plain vendored
        # Document / EmbeddedDocument classes fire it too — and have no hook.
        hook = getattr(sender, "auto_pre_init", None)
        if hook:
            hook(sender, document, **kwargs)

    @classmethod
    def from_json(cls, json_data, created=False, **kwargs):
        """Deserialize a ``to_json`` blob — and still side-load its gaps.

        ``auto_pre_init`` skips documents built from the store
        (``created=False``), but a ``to_json`` blob is NOT a full stored
        document: ``to_mongo`` omits None-valued fields, so the round trip
        can be partial. The session-restore path (``AutoAuth.current_user``)
        relies on the pk side-load filling those gaps, so construct as
        "new" (hook runs; blob values win, the store fills the rest) and
        then restore the caller's persisted-ness flag (#250).
        """
        doc = cls._from_son(bson.json_util.loads(json_data, **kwargs), created=True)
        doc._created = created
        return doc

    @classmethod
    def auto_post_init(cls, sender, document, **kwargs):
        document.last_updated = datetime.now()

    @classmethod
    def _auto_post_init(cls, sender, document, **kwargs):
        hook = getattr(sender, "auto_post_init", None)  # same guard as pre_init
        if hook:
            hook(sender, document, **kwargs)

    @property
    def path(self) -> str:
        return f"{self.model_name().lower()}/{self.pk}"

    def model_name(self, qualified: bool = False) -> str:
        """Return the model's class name (or the qualified ``module.Class``).

        Uses the Python class name rather than the mongoengine ``_class_name``
        discriminator so subclasses of non-abstract documents report their own
        name (``ChildModel``) instead of the parent-qualified form
        (``RealModel.ChildModel``) that mongoengine writes into ``_cls``.
        """
        name = type(self).__name__
        return f"{self.__module__}.{name}" if qualified else name

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
        """Resolve ``model`` (string name or class) to an ``AutoModel`` subclass.

        String resolution is memoized in module-level ``_LOAD_MODEL_CACHE``
        (additive-only — successful lookups are cached, ValueError misses
        aren't, because a subclass may be imported later). The
        ``__subclasses__()`` tree walk that runs on a cache miss is the
        unchanged legacy behavior.
        """
        if not isinstance(model, str):
            return model

        cache_key = model.lower()
        cached = _LOAD_MODEL_CACHE.get(cache_key)
        if cached is not None:
            return cached

        subclasses = AutoModel.__subclasses__()
        visited_subclasses: list[type[AutoModel]] = []
        while subclasses:
            subclass = subclasses.pop()
            if "_meta" in subclass.__dict__ and not subclass._meta.get("abstract"):
                if subclass.__name__.lower() == model.lower():
                    _LOAD_MODEL_CACHE[cache_key] = subclass
                    return subclass
            if subclass not in visited_subclasses:
                subclasses += subclass.__subclasses__()
                visited_subclasses += [subclass]
        raise ValueError(f"Model {model} not found")

    @classmethod
    def _invalidate_load_model_cache(cls) -> None:
        """Clear the load_model resolution cache. For test teardown."""
        _LOAD_MODEL_CACHE.clear()

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
    def all(cls, _select_related: bool | int = False) -> list[Self]:
        """Return every instance of this model. Use ``search`` for filtering.

        ``_select_related`` (default ``False``) opts into batch dereference of
        reference fields: ``True`` → depth 1, int ``N`` → depth ``N``. Off by
        default — behavior is unchanged for existing callers.
        """
        _ensure_connected()
        return list(_maybe_select_related(cls.objects(), _select_related))

    @classmethod
    def search(
        cls,
        _order_by: tuple[str, ...] | list[str] | None = None,
        _limit: int | list[int] | None = None,
        _select_related: bool | int = False,
        **kwargs: Any,
    ) -> list[Self]:
        """Case-insensitive substring search across the supplied fields.

        String values become ``__icontains`` queries; non-string values
        become exact matches. ``_order_by`` is forwarded to mongoengine;
        ``_limit`` accepts either a slice end or a ``[start, end]`` pair.
        ``_select_related`` (default ``False``) opts into batch dereference of
        reference fields on the returned rows: ``True`` → depth 1, int ``N`` →
        depth ``N``. Applied after ``_order_by`` / ``_limit`` so only returned
        rows are fetched. Off by default — unchanged for existing callers.
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
        results = _maybe_select_related(results, _select_related)
        return list(results)

    @classmethod
    def find(cls, **kwargs: Any) -> Self | None:
        """Return the first instance matching ``**kwargs``, or ``None``."""
        _ensure_connected()
        return cls.objects(**kwargs).first()

    @classmethod
    def where(cls, **kwargs: Any):
        """Return a chainable ``QuerySet`` for this model.

        Unlike :meth:`search` — which materializes a ``list`` — ``where``
        returns the underlying mongoengine QuerySet so consumers can
        chain ``.order_by()``, ``.limit()``, ``.skip()``, ``.only()``,
        ``.first()``, ``len()``, etc. without re-running the query.

        Uses the same ``str -> __icontains`` translation as ``search``
        for ergonomic case-insensitive substring matching:

        .. code-block:: python

            for post in Post.where(title="hello").order_by("-created")[:10]:
                ...
            author = Post.where(author_id=pk).first()
            count = Post.where(published=True).count()

        For raw mongoengine operators (``__gt``, ``__in``,
        ``__regex``...), pass them explicitly; anything other than a
        ``str`` is forwarded as-is:

        .. code-block:: python

            Post.where(views__gt=1000, tags__in=["python", "web"])
        """
        _ensure_connected()
        translated: dict[str, Any] = {}
        for k, v in kwargs.items():
            if isinstance(v, str) and "__" not in k:
                translated[f"{k}__icontains"] = v
            else:
                translated[k] = v
        return cls.objects(**translated)

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
        re-indexing via ``autonomous.db.db_sync`` — unless the model
        declares ``meta = {"vector_index": False}``. Both delete paths
        honor that flag by skipping de-index bookkeeping (#215), so
        indexing an opted-out model here would create hashes nothing
        ever removes; refusing on the normal write path is what keeps
        the flag safe to trust. Direct ``db_sync.request_indexing``
        calls are gated at enqueue time (#220) — resolving the
        document's stored class where the registry is populated — with
        a worker-side re-check at the hash write as defense-in-depth;
        anything unresolvable defaults to indexing (fail-open), so keep
        the sweep-before-flagging advice in MIGRATIONS in mind.
        """
        _ensure_connected()
        super().save()

        if sync:
            if db_sync.vector_indexed(type(self)):
                db_sync.request_indexing(
                    self.pk, collection_name=self._get_collection_name()
                )
            else:
                log(
                    f"[WARNING] save(sync=True) on {type(self).__name__}, "
                    "which declares vector_index: False — not indexing"
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

    def delete(self, signal_kwargs=None, **write_concern) -> None:
        """Delete this document from the database and drop its vector entry.

        De-indexing has no per-call flag — unlike ``save(sync=True)``,
        there is nothing to opt in with. A delete that only cleaned up
        when the caller remembered to ask would reproduce the leak this
        fixes (#204, #205): the code deleting an object is rarely the
        code that indexed it. The one opt-out is class-level (#215):
        ``meta = {"vector_index": False}`` declares the model's
        documents are never vector-indexed, so its deletes skip the
        bookkeeping entirely — a property of the model, which is exactly
        what a call site can't be trusted to know. ``save(sync=True)``
        refuses to index an opted-out model and the worker re-checks the
        flag at the hash write (#220), so the normal write paths cannot
        quietly accumulate hashes. A hash indexed BEFORE the flag was
        added still leaks when its document is deleted rather than
        re-saved — sweep once when flagging an already-indexed model
        (see MIGRATIONS). In no case can the flag strand a live
        document. ``db_sync.deindex`` is best-effort and swallows its
        own failures, so a missing or unreachable Redis costs one no-op
        call and never blocks the Mongo delete.

        Deliberately an override rather than a ``post_delete`` receiver
        alongside the four signals wired at the bottom of this module:
        ``QuerySet.delete`` checks ``has_receivers_for`` and, when a
        delete signal is connected, degrades from a single bulk
        ``delete_many`` to a per-document Python loop. Connecting one
        here would silently turn every consumer's bulk delete into N
        round-trips.

        This hook covers the single-document path only. Bulk and CASCADE
        deletes are covered at the funnel they share instead —
        ``BaseQuerySet.delete()`` collects the matched pks and calls
        ``db_sync.deindex_many`` (#207). The two are disjoint, not
        redundant: ``Document.delete()`` reaches that funnel with
        ``_from_doc_delete=True``, which skips the pk pre-scan precisely
        because this line already handled it. Raw pymongo deletes still
        bypass both — documented in MIGRATIONS.

        ``signal_kwargs`` and ``write_concern`` are pass-through: the
        signature must stay at least as wide as
        ``Document.delete(signal_kwargs=None, **write_concern)``. 0.3.171
        shipped this as a bare ``def delete(self)``, which narrowed the
        base and broke callers that never named this method — the
        funnel's skip/limit/signal branch calls ``doc.delete(**write_concern)``,
        so ``objects(...).limit(2).delete(write_concern={"w": 1})``
        raised ``TypeError`` from inside the ORM (#213).
        """
        _ensure_connected()
        # Read the pk up front: ``super().delete()`` sends ``post_delete``
        # to arbitrary consumer receivers, which are free to mutate the
        # document before we get to use it.
        pk = self.pk
        super().delete(signal_kwargs=signal_kwargs, **write_concern)
        # A never-saved document has no pk and therefore no index entry;
        # de-indexing it would issue a pointless ``DEL lore:None``. A
        # model that declared itself never-indexed has no entry either —
        # and, with Redis down, ``deindex``'s no-op costs a connect
        # timeout per delete, so the skip is worth having (#215).
        if pk is not None and db_sync.vector_indexed(type(self)):
            db_sync.deindex(pk)


signals.pre_init.connect(AutoModel._auto_pre_init)
signals.post_init.connect(AutoModel._auto_post_init)
signals.pre_save.connect(AutoModel._auto_pre_save)
signals.post_save.connect(AutoModel._auto_post_save)
