"""Independent second-perspective coverage for PR #158.

PR #158 (closes #143) replaces ``count() > 0`` with
``first() is not None`` at two existence-check sites in
``BaseQuerySet.delete``:

- DENY rule (``queryset/base.py:486-497``): raises ``OperationError``
  if any referrer exists.
- CASCADE rule (``queryset/base.py:505-518``): calls ``refs.delete(...)``
  recursively when any referrer matches.

The performance win is real but the contract the swap relies on —
``first()`` ↔ existence — is a substitution that a future "refactor
back to count for consistency" might quietly undo. These tests pin
the contract.

Dev's PR #158 ships **zero committed tests**; its coverage is
ephemeral in ``tests/_dev_local/`` (gitignored). The committed test
surface is this file alone, so the test agent owns the full
contract-pin.

Hermetic — hand-rolls the queryset / document / refs stubs needed to
drive ``BaseQuerySet.delete`` into the rule-iteration code path. The
critical stub detail (per PR #158's body): ``_skip`` and ``_limit``
must be **explicit 0** so ``call_document_delete`` evaluates falsy
at base.py:465-467 and the rule iteration runs. A ``MagicMock``
without explicit attribute control auto-generates truthy mocks for
``_skip`` / ``_limit``, routing the test down the document-delete
loop and skipping the code under test entirely.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.db.queryset.base import (
    CASCADE,
    DENY,
    NULLIFY,
    BaseQuerySet,
    OperationError,
)


# ---------------------------------------------------------------------------
# Stubs: hand-rolled, NOT MagicMock(spec=BaseQuerySet)
# ---------------------------------------------------------------------------


class _Refs:
    """Stand-in for the referrer queryset returned by
    ``document_cls.objects(...)``.

    Records whether ``.first()`` and ``.count()`` are called; lets the
    test choose what ``.first()`` returns to simulate "referrer exists"
    vs "no referrer." ``.delete()`` and ``.update()`` are no-op spies."""

    def __init__(self, first_returns):
        self._first_returns = first_returns
        self.first_calls = 0
        self.count_calls = 0
        self.delete_calls = []
        self.update_calls = []

    def first(self):
        self.first_calls += 1
        return self._first_returns

    def count(self):
        # If a future refactor reverts to ``count() > 0``, the test
        # fails immediately because the assertion at the end of each
        # test verifies ``count_calls == 0``.
        self.count_calls += 1
        return 0  # value doesn't matter — the assertion fires first

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)

    def update(self, **kwargs):
        self.update_calls.append(kwargs)


class _RefsDocClass:
    """Stand-in for the referrer document class. Its ``objects(**filter)``
    call returns the _Refs queryset the test pre-populated."""

    _meta = {"abstract": False}
    _collection = "refs_collection"
    __name__ = "RefsDoc"

    def __init__(self, refs):
        self._refs = refs

    def objects(self, **filter_kwargs):
        return self._refs


class _DocClass:
    """Stand-in for ``queryset._document``. Carries ``_meta`` with the
    test's chosen ``delete_rules`` dict."""

    def __init__(self, delete_rules):
        self._meta = {"delete_rules": delete_rules}
        self._collection = "doc_collection"


def _self_queryset(doc, *, skip=0, limit=0):
    """Build the ``self`` queryset that BaseQuerySet.delete operates on.

    Plain class with EXPLICIT ``_skip = 0`` / ``_limit = 0`` so the
    ``call_document_delete`` evaluation at base.py:465-467 is falsy
    and the rule-iteration code runs. A MagicMock would auto-generate
    truthy mocks here and route the test down the doc-delete loop.
    """
    class _SelfQS:
        _skip = skip
        _limit = limit
        _none = False
        _empty = False
        _hint = None
        _collation = None
        _query = {}
        _collection = MagicMock()
        _document = doc

        def clone(self):
            return self

        def __iter__(self):
            return iter([])

    return _SelfQS()


@pytest.fixture(autouse=True)
def _no_signal_receivers(monkeypatch):
    """``has_delete_signal`` adds ``call_document_delete = True`` if
    receivers are registered. Force-clear to keep the rule iteration
    reachable in unit tests where signals from prior tests may
    linger."""
    from autonomous.db import signals as _signals

    def _no_receivers(_sender):
        return False

    monkeypatch.setattr(
        _signals.pre_delete, "has_receivers_for", _no_receivers
    )
    monkeypatch.setattr(
        _signals.post_delete, "has_receivers_for", _no_receivers
    )


@pytest.fixture
def _stub_collection_writes():
    """The actual ``collection.delete_many`` call at base.py:529 needs
    a stubable collection. The ``set_write_concern`` context manager
    yields ``queryset._collection`` — we patch it module-level so the
    yield returns a MagicMock whose ``delete_many`` is a no-op."""
    with patch(
        "autonomous.db.queryset.base.set_write_concern"
    ) as mock_swc:
        result_stub = MagicMock()
        result_stub.acknowledged = True
        result_stub.deleted_count = 0
        collection_stub = MagicMock()
        collection_stub.delete_many.return_value = result_stub
        mock_swc.return_value.__enter__.return_value = collection_stub
        mock_swc.return_value.__exit__.return_value = False
        yield


# ===========================================================================
# 1. DENY rule — raises only when refs exist
# ===========================================================================


class TestDenyRaisesWhenFirstReturnsObject:
    """``DENY`` arm raises ``OperationError`` when ``refs.first()``
    returns any non-None document (one referrer is enough to deny)."""

    def test_referrer_exists_raises_operation_error(
        self, _stub_collection_writes
    ):
        refs = _Refs(first_returns=object())  # any non-None
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): DENY})
        self_qs = _self_queryset(doc)

        with pytest.raises(OperationError) as exc_info:
            BaseQuerySet.delete(self_qs)

        # Message identifies the referring class and field — pins the
        # error message format so a refactor that drops the class/
        # field detail surfaces here.
        assert "RefsDoc.fk_field" in str(exc_info.value)
        # ``first()`` was called exactly once (the existence check).
        assert refs.first_calls == 1
        # ``count()`` was NEVER called — the perf win contract.
        assert refs.count_calls == 0

    def test_no_referrer_does_not_raise(self, _stub_collection_writes):
        refs = _Refs(first_returns=None)
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): DENY})
        self_qs = _self_queryset(doc)

        # Must NOT raise.
        BaseQuerySet.delete(self_qs)

        assert refs.first_calls == 1
        assert refs.count_calls == 0


class TestDenyAbstractDocumentClassIsSkipped:
    """A referring class marked ``_meta["abstract"] = True`` is
    skipped over (base.py:483-484 ``if document_cls._meta.get("abstract")``).
    Pin that the abstract-skip happens BEFORE either ``first()`` or
    ``count()`` is touched."""

    def test_abstract_referrer_does_not_query(self, _stub_collection_writes):
        refs = _Refs(first_returns=object())  # would raise if queried
        refs_cls = _RefsDocClass(refs)
        refs_cls._meta = {"abstract": True}
        doc = _DocClass({(refs_cls, "fk_field"): DENY})
        self_qs = _self_queryset(doc)

        # Must NOT raise — the abstract class is skipped before the
        # existence check fires.
        BaseQuerySet.delete(self_qs)

        assert refs.first_calls == 0
        assert refs.count_calls == 0


# ===========================================================================
# 2. CASCADE rule — recurses only when refs exist
# ===========================================================================


class TestCascadeDeletesWhenFirstReturnsObject:
    """``CASCADE`` arm calls ``refs.delete(...)`` when ``refs.first()``
    returns any non-None document."""

    def test_referrer_exists_triggers_cascade_delete(
        self, _stub_collection_writes
    ):
        refs = _Refs(first_returns=object())
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): CASCADE})
        self_qs = _self_queryset(doc)

        BaseQuerySet.delete(self_qs)

        # Recursive delete fired exactly once with the write_concern
        # kwarg forwarded.
        assert len(refs.delete_calls) == 1
        assert "write_concern" in refs.delete_calls[0]
        assert "cascade_refs" in refs.delete_calls[0]
        assert refs.first_calls == 1
        assert refs.count_calls == 0

    def test_no_referrer_skips_cascade_delete(self, _stub_collection_writes):
        refs = _Refs(first_returns=None)
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): CASCADE})
        self_qs = _self_queryset(doc)

        BaseQuerySet.delete(self_qs)

        # Cascade delete NEVER fires when there's nothing to cascade —
        # documented at PR #158 as the rule-rebuilding-cost-avoidance
        # invariant.
        assert refs.delete_calls == []
        assert refs.first_calls == 1
        assert refs.count_calls == 0


# ===========================================================================
# 3. The performance contract — count() is never called on either arm
# ===========================================================================


class TestCountIsNeverCalledOnExistenceCheck:
    """The whole point of PR #158: neither DENY nor CASCADE should
    ever call ``.count()`` on the refs queryset. The _Refs stub
    increments ``count_calls`` and these tests assert it stays 0."""

    @pytest.mark.parametrize(
        "rule,first_returns,refs_should_raise",
        [
            (DENY, object(), True),
            (DENY, None, False),
            (CASCADE, object(), False),
            (CASCADE, None, False),
        ],
        ids=["DENY+exists", "DENY+empty", "CASCADE+exists", "CASCADE+empty"],
    )
    def test_count_never_called(
        self, rule, first_returns, refs_should_raise, _stub_collection_writes
    ):
        refs = _Refs(first_returns=first_returns)
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): rule})
        self_qs = _self_queryset(doc)

        if refs_should_raise:
            with pytest.raises(OperationError):
                BaseQuerySet.delete(self_qs)
        else:
            BaseQuerySet.delete(self_qs)

        assert refs.count_calls == 0, (
            f"refs.count() called {refs.count_calls} time(s) — the "
            f"PR #158 perf contract was reverted to count()-based "
            f"existence checks"
        )


# ===========================================================================
# 4. Multi-rule interaction — DENY pass happens BEFORE the CASCADE pass
# ===========================================================================


class TestDenyShortCircuitsBeforeCascade:
    """``BaseQuerySet.delete`` iterates DENY rules FIRST (base.py:481-
    497), then iterates the other rules (base.py:500+). A doc with
    both a DENY referrer (that exists) and a CASCADE referrer should:
    1. Raise OperationError from the DENY check.
    2. Never run the CASCADE check (so the CASCADE refs.first() is
       NOT called).

    Pin so a refactor that fuses the two loops doesn't silently
    invert the precedence."""

    def test_deny_raise_prevents_cascade_existence_check(
        self, _stub_collection_writes
    ):
        deny_refs = _Refs(first_returns=object())
        cascade_refs = _Refs(first_returns=object())
        deny_cls = _RefsDocClass(deny_refs)
        deny_cls.__name__ = "DenyRefs"
        cascade_cls = _RefsDocClass(cascade_refs)
        cascade_cls.__name__ = "CascadeRefs"

        # Both rules registered — order in the dict doesn't matter
        # because BaseQuerySet.delete iterates DENY first via the
        # explicit two-pass loop.
        doc = _DocClass({
            (cascade_cls, "cascade_fk"): CASCADE,
            (deny_cls, "deny_fk"): DENY,
        })
        self_qs = _self_queryset(doc)

        with pytest.raises(OperationError) as exc_info:
            BaseQuerySet.delete(self_qs)

        assert "DenyRefs.deny_fk" in str(exc_info.value)
        # DENY existence check ran.
        assert deny_refs.first_calls == 1
        # CASCADE check did NOT run — DENY raise short-circuited the
        # second loop entirely.
        assert cascade_refs.first_calls == 0
        assert cascade_refs.delete_calls == []


class TestNullifyRuleDoesNotUseFirstOrCount:
    """The PR only changes DENY + CASCADE — NULLIFY (and PULL) are
    untouched. Verify the negative space: ``NULLIFY`` calls
    ``.update(...)`` directly without an existence check, so neither
    ``first()`` nor ``count()`` should fire on the refs queryset for
    a pure-NULLIFY rule."""

    def test_nullify_calls_update_without_existence_check(
        self, _stub_collection_writes
    ):
        refs = _Refs(first_returns=object())
        refs_cls = _RefsDocClass(refs)
        doc = _DocClass({(refs_cls, "fk_field"): NULLIFY})
        self_qs = _self_queryset(doc)

        BaseQuerySet.delete(self_qs)

        # NULLIFY went straight to update without consulting first()
        # or count() — pins that PR #158's swap didn't accidentally
        # add an existence gate to the other rule arms.
        assert refs.first_calls == 0
        assert refs.count_calls == 0
        assert len(refs.update_calls) == 1
