"""Test-agent coverage for #213 — ``AutoModel.delete()`` narrowed
``Document.delete()``'s signature.

Shipped in 0.3.171 (#204, #205) and found while tracing #207. The
override was written as ``def delete(self) -> None`` against a base of
``Document.delete(self, signal_kwargs=None, **write_concern)``, which
narrows an existing public signature rather than adding to it:

- ``obj.delete(signal_kwargs={...})`` — a documented mongoengine-style
  call — became a hard ``TypeError``.
- ``obj.delete(w=1)`` and every other write concern hit the same
  ``TypeError``.
- Worst, ``BaseQuerySet.delete()``'s skip/limit/connected-signal branch
  early-returns to ``for doc in queryset: doc.delete(**write_concern)``,
  so ``Model.objects(...).limit(2).delete(write_concern={"w": 1})``
  raised ``TypeError: delete() got an unexpected keyword argument 'w'``
  from inside the ORM — a caller that never touched ``AutoModel.delete``
  directly.

The fix lands on ``test`` rather than in dev's PR #214 because it
collides with a committed pin on this agent's own surface
(``test_unit_deindex_on_delete_iter_2026_08_14.py``'s
``params == ["self"]``), and the dev tree does not edit ``tests/unit/``.
That pin's stated intent was only "no opt-in ``sync=`` flag"; it is
restated there in terms of that intent plus base-class compatibility,
so the two guards no longer contradict each other.

Every test here was seen failing against the unfixed override first —
the three call shapes raised ``TypeError``, and the compatibility pin
reported ``['self']``.

Hermetic: ``Document.delete`` is patched to a spy, so no Mongo. The
de-index seam is patched too, so no Redis.
"""

from __future__ import annotations

import inspect

import pytest

from autonomous.db import Document
from autonomous.db.queryset.base import BaseQuerySet
from autonomous.model import automodel as am


@pytest.fixture
def delete_spy(monkeypatch):
    """A real ``AutoModel`` subclass whose base ``delete`` records what
    it was handed.

    A real subclass, not a stub: ``AutoModel.delete`` calls zero-arg
    ``super()``, which needs an actual instance. ``Document.delete`` is
    the next ``delete`` in the MRO, so patching it there intercepts the
    ORM write without a live Mongo.
    """

    class _SignatureProbeDoc(am.AutoModel):
        pass

    calls = []
    deindexed = []

    def _super_delete(self, *args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(Document, "delete", _super_delete)
    monkeypatch.setattr(am.db_sync, "deindex", lambda pk: deindexed.append(pk) or True)
    monkeypatch.setattr(am, "_ensure_connected", lambda *a, **kw: None)
    return _SignatureProbeDoc, calls, deindexed


@pytest.fixture(autouse=True)
def _no_signal_receivers(monkeypatch):
    """Keeps ``call_document_delete`` keyed to ``_limit`` alone, rather
    than to whatever receivers an earlier test left registered."""
    from autonomous.db import signals as _signals

    monkeypatch.setattr(_signals.pre_delete, "has_receivers_for", lambda _s: False)
    monkeypatch.setattr(_signals.post_delete, "has_receivers_for", lambda _s: False)


# ===========================================================================
# 1. The three call shapes #213 broke
# ===========================================================================


class TestDirectCallShapes:
    def test_signal_kwargs_is_accepted_and_forwarded(self, delete_spy):
        # mongoengine's documented way to pass context to pre/post_delete
        # receivers. Pre-fix this raised TypeError, so a consumer that
        # relied on it could not upgrade past 0.3.171 at all.
        cls, calls, _ = delete_spy
        obj = cls()
        obj.pk = "abc123"

        obj.delete(signal_kwargs={"reason": "gdpr"})

        assert calls[0]["kwargs"].get("signal_kwargs") == {"reason": "gdpr"}, (
            f"signal_kwargs must reach Document.delete; got {calls!r}"
        )

    def test_write_concern_is_accepted_and_forwarded(self, delete_spy):
        # Silently dropping it would be worse than the TypeError: the
        # caller believes the delete waited for two nodes and it did not.
        cls, calls, _ = delete_spy
        obj = cls()
        obj.pk = "abc123"

        obj.delete(w=2, j=True)

        kwargs = calls[0]["kwargs"]
        assert kwargs.get("w") == 2 and kwargs.get("j") is True, (
            f"write concern must reach Document.delete; got {calls!r}"
        )

    def test_both_together(self, delete_spy):
        cls, calls, _ = delete_spy
        obj = cls()
        obj.pk = "abc123"

        obj.delete(signal_kwargs={"reason": "x"}, w=1)

        assert calls[0]["kwargs"] == {"signal_kwargs": {"reason": "x"}, "w": 1}

    def test_bare_call_still_works(self, delete_spy):
        # The overwhelmingly common shape; the widening must not make
        # anything mandatory.
        cls, calls, deindexed = delete_spy
        obj = cls()
        obj.pk = "abc123"

        obj.delete()

        assert calls[0]["kwargs"].get("signal_kwargs") is None
        assert deindexed == ["abc123"]


# ===========================================================================
# 2. The QuerySet path — a caller who never names ``delete`` themselves
# ===========================================================================


class _LimitedQuerySet:
    """The skip/limit/signal branch of ``BaseQuerySet.delete``.

    That branch cannot use ``delete_many`` (Mongo has no "delete the
    first N matching"), so it early-returns to a per-document loop:
    ``for doc in queryset: doc.delete(**write_concern)``. With a narrowed
    override, that loop raises from inside the ORM.
    """

    _skip = 0
    _limit = 2
    _query = {}
    _collection = None

    def __init__(self, docs, document_cls):
        self._docs = list(docs)
        self._document = document_cls

    def clone(self):
        return self

    def __iter__(self):
        return iter(self._docs)


class TestQuerySetLimitDeletePath:
    def test_limit_delete_with_write_concern_does_not_raise(self, delete_spy):
        # The reported repro: objects(...).limit(2).delete(
        #     write_concern={"w": 1}) → TypeError before the fix.
        cls, calls, _ = delete_spy
        docs = []
        for pk in ("a", "b"):
            obj = cls()
            obj.pk = pk
            docs.append(obj)
        qs = _LimitedQuerySet(docs, cls)

        assert BaseQuerySet.delete(qs, write_concern={"w": 1}) == 2

        assert [c["kwargs"].get("w") for c in calls] == [1, 1], (
            f"each document delete must carry the write concern; got {calls!r}"
        )

    def test_limit_delete_still_deindexes_each_document(self, delete_spy):
        # The widening must not cost the 0.3.171 behavior: this branch is
        # the one path where per-document de-indexing is the only
        # de-indexing that happens (it never reaches delete_many, so the
        # #207 funnel hook does not fire).
        cls, _, deindexed = delete_spy
        docs = []
        for pk in ("a", "b"):
            obj = cls()
            obj.pk = pk
            docs.append(obj)

        BaseQuerySet.delete(_LimitedQuerySet(docs, cls), write_concern={"w": 1})

        assert deindexed == ["a", "b"]

    def test_limit_delete_without_write_concern_still_works(self, delete_spy):
        cls, calls, _ = delete_spy
        obj = cls()
        obj.pk = "a"

        assert BaseQuerySet.delete(_LimitedQuerySet([obj], cls)) == 1
        # ``signal_kwargs=None`` is the base's own default, so forwarding
        # it explicitly is a no-op; inventing a write concern would not be.
        assert "w" not in calls[0]["kwargs"]
        assert calls[0]["kwargs"].get("signal_kwargs") is None


# ===========================================================================
# 3. Structural pin — an override may widen a base signature, never
#    narrow one
# ===========================================================================


class TestSignatureCompatibility:
    def test_accepts_everything_document_delete_accepts(self):
        # The general form of #213: a call that binds against the base
        # must bind against the override, or the override is not
        # substitutable for it. Binding is checked rather than comparing
        # parameter lists so the override stays free to add its own.
        base = inspect.signature(Document.delete)
        override = inspect.signature(am.AutoModel.delete)
        probe = object()

        base.bind(probe, signal_kwargs={"a": 1}, w=1, j=True)
        override.bind(probe, signal_kwargs={"a": 1}, w=1, j=True)

    def test_still_takes_no_opt_in_deindex_flag(self):
        # The other half of the pin restated in
        # test_unit_deindex_on_delete_iter_2026_08_14.py: de-indexing is
        # unconditional. A keyword-only ``sync=`` defaulting to False
        # would silently restore #204's leak for every existing caller,
        # and ``**write_concern`` would swallow it without a TypeError.
        params = list(inspect.signature(am.AutoModel.delete).parameters)
        assert "sync" not in params, (
            f"delete() must not gain an opt-in de-index flag; got {params!r}"
        )

    def test_write_concern_is_variadic_not_a_named_dict(self):
        # ``Document.delete`` collects write concern via **kwargs, and
        # the funnel splats a dict into it (``doc.delete(**write_concern)``).
        # An override taking ``write_concern=None`` instead would accept
        # the call and then quietly send ``{"write_concern": {...}}``
        # nowhere.
        params = inspect.signature(am.AutoModel.delete).parameters
        assert any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        ), f"delete() must keep **write_concern variadic; got {list(params)!r}"
