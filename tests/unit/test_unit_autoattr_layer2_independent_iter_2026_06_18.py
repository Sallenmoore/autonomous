"""Independent second-perspective coverage for PR #155 / issue #141.

PR #155 ships pinning tests for the Layer-2 customizations in
``autonomous.model.autoattr`` and ``autonomous.model.automodel`` —
``IntAttr``, ``ListAttr`` (get + set), ``DictAttr``, ``ReferenceAttr``,
``AutoModel.get()``. This file is the test agent's **independent**
second-perspective coverage of the same Layer-2 surface, written from a
fresh read of ``autoattr.py`` / ``automodel.py`` /
``src/autonomous/db/DIVERGENCE.md`` rather than from dev's tests.

The corners pinned here are the ones dev's tests did **not** pin —
chosen because they're the kind a refactor is most likely to break
silently:

- ``IntAttr.__set__``: composition of comma-strip + regex (negative with
  commas, whitespace, leading zeros, decimals, currency-with-commas-and-
  minus), and the "first integer wins" semantics when the regex matches
  multiple substrings.
- ``ListAttr.__set__``: empty entries that survive split (leading /
  trailing separators), and whitespace-only strings that aren't empty.
- ``ListAttr.__get__``: the **guard** — non-``ReferenceAttr`` element
  types must NOT prune falsy entries. Dev pins the prune branch; this
  file pins the no-prune branch. Plus a non-adjacent prune pattern to
  rule out an off-by-one different from the consecutive-falsy case
  dev pinned.
- ``DictAttr.__get__``: the asymmetric-with-``ListAttr`` invariant
  (side-by-side: same stale ref, list prunes, dict keeps), and the
  in-place write-back of resolved values into the underlying ``_data``.
- ``ReferenceAttr.__get__``: only ``DoesNotExist`` is swallowed —
  other exceptions must propagate. Dev pins the swallow; this file
  pins the propagation.
- ``AutoModel.get()``: the pk-coercion ladder branches that dev didn't
  exercise (``{"$oid": ...}`` dict form, already-an-``ObjectId``
  pass-through, ``None`` pk reaching the QuerySet).

Hermetic — no MongoDB connection. Stubs are rebuilt independently of
dev's ``_make_doc`` helpers so the two perspectives don't share a
single failure surface.
"""

from unittest.mock import MagicMock, patch

import bson
import pytest
from pymongo.errors import ConnectionFailure, OperationFailure

from autonomous.db import DoesNotExist
from autonomous.model.autoattr import (
    DictAttr,
    IntAttr,
    ListAttr,
    ReferenceAttr,
    StringAttr,
)


# ---------------------------------------------------------------------------
# Independent stub builder — minimal, rebuilt from scratch (not dev's _make_doc)
# ---------------------------------------------------------------------------


def _stub_doc(field_name, stored, field=None):
    """Return a minimal initialised-document stub.

    ``field`` is forwarded into ``_fields`` so the upstream
    ``BaseField.__get__`` descriptor can read
    ``instance._fields[name]._auto_dereference`` on collection-typed
    descriptors (``ListAttr`` / ``DictAttr``).
    """
    fields = {field_name: field} if field is not None else {}

    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields: dict = {}
        _db_field_map = {field_name: field_name}
        _data = {field_name: stored}
        _fields = fields
        _changed_fields: list[str] = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


# ---------------------------------------------------------------------------
# IntAttr — composition corners the dev tree didn't pin
# ---------------------------------------------------------------------------


class TestIntAttrCompositionCorners:
    """``IntAttr.__set__`` corners arising from comma-strip + regex ordering."""

    @pytest.fixture
    def field(self):
        f = IntAttr()
        f.name = "count"
        f.db_field = "count"
        f.null = True
        f.default = None
        return f

    def test_negative_with_thousands_comma(self, field):
        # The comma-strip runs first, so "-1,000" becomes "-1000". That
        # isn't ``.isdigit()`` (the leading minus disqualifies it), so
        # the regex ``r"-?\d+"`` fires and matches "-1000". The
        # composition of the two passes is the contract: comma-strip
        # must NOT happen as a final step (otherwise the result would
        # be ``int("-1000")`` only via the regex, which still works —
        # but a refactor that swaps the order or skips the comma-strip
        # on the regex path would surface as ``-1`` here).
        doc = _stub_doc("count", None)
        field.__set__(doc, "-1,000")
        assert doc._data["count"] == -1000

    def test_whitespace_around_digits(self, field):
        # " 42 " is not ``.isdigit()`` (whitespace fails the check), so
        # the regex fallback fires and extracts 42. Pins a documented-
        # ergonomics corner for form-trim laziness.
        doc = _stub_doc("count", None)
        field.__set__(doc, " 42 ")
        assert doc._data["count"] == 42

    def test_first_integer_wins_with_multiple_matches(self, field):
        # The regex is non-greedy in the "first-match" sense: re.search
        # returns the leftmost match, so "42 99 100" yields 42 and the
        # remaining integers are discarded. Pin this so a future
        # refactor to ``re.findall`` doesn't quietly change "first" to
        # "last" or "concatenated".
        doc = _stub_doc("count", None)
        field.__set__(doc, "42 99 100")
        assert doc._data["count"] == 42

    def test_leading_zero_numeric_string(self, field):
        # "007" passes ``.isdigit()`` so the isdigit branch fires:
        # ``int("007")`` → 7. The leading zero is silently dropped.
        # Surprising for callers who treat the field like a fixed-width
        # identifier (employee codes, ZIP-prefix), so it's worth a
        # named pin.
        doc = _stub_doc("count", None)
        field.__set__(doc, "007")
        assert doc._data["count"] == 7

    def test_decimal_string_truncates_at_dot(self, field):
        # "3.14" is not ``.isdigit()`` (the dot disqualifies it), so the
        # regex fires and matches the first integer substring "3". The
        # ``.14`` is silently discarded — Python's int() would have
        # raised on "3.14"; the regex fallback eats the error.
        doc = _stub_doc("count", None)
        field.__set__(doc, "3.14")
        assert doc._data["count"] == 3

    def test_currency_with_minus_and_intervening_non_digit_drops_sign(self, field):
        # Full composition: "-$1,234.56" comma-strip → "-$1234.56" not
        # isdigit → regex ``r"-?\d+"`` scans for the FIRST position
        # where ``\d+`` matches. The "-" at position 0 can't anchor a
        # match because position 1 is "$", not a digit, so the engine
        # advances and matches at position 2 with ``-?`` consuming
        # zero chars and ``\d+`` matching "1234". Net: the minus
        # silently disappears whenever a non-digit character sits
        # between it and the first digit run. NON-OBVIOUS — callers
        # who feed signed currency through this descriptor will get
        # the absolute value, not the negative. Pinning this surfaces
        # the corner so a refactor either preserves it or fixes it
        # deliberately.
        doc = _stub_doc("count", None)
        field.__set__(doc, "-$1,234.56")
        assert doc._data["count"] == 1234


# ---------------------------------------------------------------------------
# ListAttr.__set__ — empty-entry survival corners
# ---------------------------------------------------------------------------


class TestListAttrSetEmptyEntryCorners:
    """``ListAttr.__set__`` corners around leading / trailing separators."""

    @pytest.fixture
    def field(self):
        f = ListAttr(StringAttr())
        f.name = "tags"
        f.db_field = "tags"
        f.null = True
        f.default = list
        return f

    def test_trailing_semicolon_produces_empty_tail(self, field):
        # ``"a;".split(";")`` is ``["a", ""]``. The strip step preserves
        # the empty string. Pin this so a refactor that filters empty
        # entries (a tempting cleanup) doesn't silently change list
        # length.
        doc = _stub_doc("tags", None)
        field.__set__(doc, "a;")
        assert doc._data["tags"] == ["a", ""]

    def test_leading_semicolon_produces_empty_head(self, field):
        # Symmetric with trailing — the head element is empty after
        # split + strip.
        doc = _stub_doc("tags", None)
        field.__set__(doc, ";a")
        assert doc._data["tags"] == ["", "a"]

    def test_trailing_comma_produces_empty_tail(self, field):
        # Comma-fallback branch shares the same survival semantic with
        # semicolon. Worth a parallel pin because the two branches
        # could drift independently.
        doc = _stub_doc("tags", None)
        field.__set__(doc, "a,")
        assert doc._data["tags"] == ["a", ""]

    def test_whitespace_only_string_is_single_element(self, field):
        # ``"   "`` has no separators and is truthy (the ``if value:``
        # check at autoattr.py:153 evaluates the string, not its
        # stripped form), so it becomes ``["   "]`` — a one-element
        # list containing the whitespace. NOT ``[]`` despite "looking
        # empty" to a human. Pins the by-design distinction between
        # ``""`` (→ ``[]``) and ``"   "`` (→ ``["   "]``).
        doc = _stub_doc("tags", None)
        field.__set__(doc, "   ")
        assert doc._data["tags"] == ["   "]

    def test_semicolon_precedence_preserves_commas_with_whitespace(self, field):
        # Cross-corner: semicolon precedence + surrounding whitespace
        # + embedded commas. After semicolon split + per-element strip,
        # the commas inside an element survive verbatim (no comma
        # split is applied because the ``;`` branch consumed the input
        # first).
        doc = _stub_doc("tags", None)
        field.__set__(doc, "  a ; b , c  ")
        assert doc._data["tags"] == ["a", "b , c"]


# ---------------------------------------------------------------------------
# ListAttr.__get__ — the no-prune branch (the critical guard)
# ---------------------------------------------------------------------------


class TestListAttrGetGuardBranch:
    """``ListAttr.__get__`` does NOT prune when ``self.field`` is non-reference.

    The reference-pruning loop at ``autoattr.py:134-143`` is gated by
    ``isinstance(self.field, ReferenceAttr)``. Dev's tests pin the
    pruning branch; these pin the guard so a refactor that removes the
    isinstance check (e.g. "prune everywhere for consistency") gets
    caught.
    """

    @pytest.fixture
    def string_list_field(self):
        # ListAttr(StringAttr()) — the element type is NOT ReferenceAttr,
        # so the prune loop must be skipped.
        f = ListAttr(StringAttr())
        f.name = "items"
        f.db_field = "items"
        f.null = True
        f.default = list
        return f

    def test_none_entries_survive_in_non_reference_list(self, string_list_field):
        # If the prune loop ran unconditionally, ``None`` would be
        # popped here. The isinstance guard must prevent that.
        doc = _stub_doc("items", ["a", None, "b"], field=string_list_field)
        result = string_list_field.__get__(doc, type(doc))
        assert result == ["a", None, "b"]

    def test_empty_string_entries_survive_in_non_reference_list(self, string_list_field):
        # Empty strings are falsy. They'd be candidate prune targets
        # under the broken (no-guard) version. The guard preserves
        # them.
        doc = _stub_doc("items", ["a", "", "b", ""], field=string_list_field)
        result = string_list_field.__get__(doc, type(doc))
        assert result == ["a", "", "b", ""]

    def test_zero_entries_survive_in_non_reference_list(self, string_list_field):
        # ``0`` is falsy. Same prune-vs-keep risk as None/"".
        doc = _stub_doc("items", [1, 0, 2, 0, 3], field=string_list_field)
        result = string_list_field.__get__(doc, type(doc))
        assert result == [1, 0, 2, 0, 3]


class _TruthyRefStub:
    """Stand-in for a resolved reference — always truthy under bool()."""

    def __init__(self, tag):
        self.tag = tag

    def __bool__(self):
        return True


class TestListAttrGetNonAdjacentPrune:
    """Off-by-one regression coverage independent of dev's adjacent-falsy pin.

    Dev pins the consecutive-falsy case (the ``[a, None, None]`` shape).
    This class pins the non-adjacent pattern (``[a, None, b, None, c]``)
    so a refactor that breaks ordering on alternating falsy entries
    surfaces a different signal than the adjacent case.
    """

    @pytest.fixture
    def ref_list_field(self):
        f = ListAttr(ReferenceAttr())
        f.name = "refs"
        f.db_field = "refs"
        f.null = True
        f.default = list
        return f

    def test_alternating_none_entries_pruned_preserve_order(self, ref_list_field):
        a, b, c = _TruthyRefStub("a"), _TruthyRefStub("b"), _TruthyRefStub("c")
        doc = _stub_doc("refs", [a, None, b, None, c], field=ref_list_field)
        result = ref_list_field.__get__(doc, type(doc))
        # Ordering is the substantive part — bare equality could pass
        # for any 3-element subset, so assert the labels explicitly.
        assert [item.tag for item in result] == ["a", "b", "c"]

    def test_all_none_collapses_to_empty(self, ref_list_field):
        doc = _stub_doc("refs", [None, None, None], field=ref_list_field)
        result = ref_list_field.__get__(doc, type(doc))
        assert result == []


# ---------------------------------------------------------------------------
# DictAttr — asymmetric-with-ListAttr + write-back
# ---------------------------------------------------------------------------


class _StaleLazyRef:
    """A lazy reference whose ``.fetch()`` raises ``DoesNotExist``."""

    pk = "stale"

    def fetch(self):
        raise DoesNotExist

    def __bool__(self):
        # Important for the ListAttr comparison side: the prune branch
        # in ListAttr.__get__ checks ``not results[i]`` first, so a
        # stale ref needs to be falsy for the list side to prune.
        return False


class _ResolvableLazyRef:
    """A lazy reference whose ``.fetch()`` returns a resolved value."""

    def __init__(self, pk, resolved):
        self.pk = pk
        self._resolved = resolved

    def fetch(self):
        return self._resolved


class TestDictAttrAsymmetryWithListAttr:
    """The list-prunes / dict-keeps invariant, pinned side-by-side.

    DIVERGENCE.md §`DictAttr`: "Missing referents are logged and the
    placeholder is left in place rather than pruned (asymmetric with
    `ListAttr` — a dict's keys are usually meaningful, so we preserve
    the key even when the value can't be resolved)."

    Pinning the two behaviors next to each other catches a refactor
    that aligns them in either direction.
    """

    def test_stale_ref_list_prunes_dict_keeps(self):
        list_field = ListAttr(ReferenceAttr())
        list_field.name = "refs"
        list_field.db_field = "refs"
        list_field.null = True
        list_field.default = list

        dict_field = DictAttr()
        dict_field.name = "refs"
        dict_field.db_field = "refs"
        dict_field.null = True
        dict_field.default = dict

        stale = _StaleLazyRef()

        list_doc = _stub_doc("refs", [stale], field=list_field)
        dict_doc = _stub_doc("refs", {"k": stale}, field=dict_field)

        with patch("autonomous.model.autoattr.log"):
            list_result = list_field.__get__(list_doc, type(list_doc))
            dict_result = dict_field.__get__(dict_doc, type(dict_doc))

        # The list side prunes the stale ref entirely.
        assert list_result == []
        # The dict side preserves the key with the placeholder value.
        assert "k" in dict_result
        assert dict_result["k"] is stale


class TestDictAttrWriteBack:
    """``DictAttr.__get__`` writes resolved values back into underlying _data."""

    @pytest.fixture
    def field(self):
        f = DictAttr()
        f.name = "props"
        f.db_field = "props"
        f.null = True
        f.default = dict
        return f

    def test_resolved_value_is_persisted_into_underlying_dict(self, field):
        # The ``results[key] = lazy_obj`` write at autoattr.py:179 is
        # an in-place mutation of the dict returned by
        # ``super().__get__``, which IS the same object stored at
        # ``instance._data[name]``. So a second call to __get__ should
        # see the resolved value directly (the resolved object does
        # not have ``.fetch()``, so the deref branch is skipped).
        resolved = object()  # no .fetch() method
        lazy = _ResolvableLazyRef(pk="x", resolved=resolved)
        doc = _stub_doc("props", {"key": lazy}, field=field)

        # First call resolves.
        first = field.__get__(doc, type(doc))
        assert first["key"] is resolved

        # Underlying _data is mutated in place.
        assert doc._data["props"]["key"] is resolved

        # Second call returns the resolved value without re-fetching
        # (the resolved object has no .fetch(), so the deref branch
        # is skipped — if write-back had failed, the first call
        # would mutate the dict back to the lazy_obj and we'd hit
        # this branch).
        second = field.__get__(doc, type(doc))
        assert second["key"] is resolved


# ---------------------------------------------------------------------------
# ReferenceAttr.__get__ — propagation of non-DoesNotExist exceptions
# ---------------------------------------------------------------------------


class TestReferenceAttrGetExceptionPropagation:
    """``ReferenceAttr.__get__`` swallows ONLY ``DoesNotExist``.

    Dev pins the swallow; this class pins the contrapositive — other
    exception types must propagate. A refactor that broadens the
    except clause to ``Exception`` (a common "defensive" mistake)
    would silently turn every reference failure into ``None``,
    masking real bugs.
    """

    @pytest.fixture
    def field(self):
        f = ReferenceAttr()
        f.name = "ref"
        f.db_field = "ref"
        f.null = True
        f.default = None
        return f

    def test_value_error_propagates(self, field, monkeypatch):
        from autonomous.db.fields import GenericReferenceField

        def _raises_value_error(self, instance, owner):
            raise ValueError("not a DoesNotExist")

        monkeypatch.setattr(GenericReferenceField, "__get__", _raises_value_error)

        doc = _stub_doc("ref", None)

        with pytest.raises(ValueError, match="not a DoesNotExist"):
            field.__get__(doc, type(doc))

    def test_runtime_error_propagates(self, field, monkeypatch):
        from autonomous.db.fields import GenericReferenceField

        def _raises_runtime(self, instance, owner):
            raise RuntimeError("infra blew up")

        monkeypatch.setattr(GenericReferenceField, "__get__", _raises_runtime)

        doc = _stub_doc("ref", None)

        with pytest.raises(RuntimeError, match="infra blew up"):
            field.__get__(doc, type(doc))


# ---------------------------------------------------------------------------
# AutoModel.get() — pk-coercion ladder branches dev didn't exercise
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_model():
    """Independently-built AutoModel stand-in with stubbed ``objects``."""
    from autonomous.model import automodel as am

    class _FakeDoesNotExist(Exception):
        pass

    class Fake:
        objects = MagicMock()
        DoesNotExist = _FakeDoesNotExist
        __name__ = "Fake"

    Fake.get = classmethod(am.AutoModel.get.__func__)
    return Fake


@pytest.fixture(autouse=True)
def _skip_ensure_connected_independent():
    from autonomous.model import automodel as am

    with patch.object(am, "_ensure_connected"):
        yield


class TestAutoModelGetPkVariants:
    """``AutoModel.get`` pk-coercion ladder corners (automodel.py:254-260)."""

    def test_extended_json_oid_dict_form_is_coerced(self, fake_model):
        # The elif branch at automodel.py:259-260 handles the BSON
        # extended-JSON form ``{"$oid": "<hex>"}``. Pin that the value
        # arriving at ``objects.get(id=...)`` is the coerced ObjectId,
        # not the raw dict.
        sentinel = object()
        fake_model.objects.get.return_value = sentinel
        oid = bson.ObjectId()

        result = fake_model.get({"$oid": str(oid)})

        assert result is sentinel
        call_kwargs = fake_model.objects.get.call_args.kwargs
        assert isinstance(call_kwargs["id"], bson.ObjectId)
        assert call_kwargs["id"] == oid

    def test_already_objectid_passes_through(self, fake_model):
        # A real ``bson.ObjectId`` is neither str nor a $oid dict, so
        # neither coercion branch fires — pk reaches objects.get(id=)
        # unchanged. Pins the no-double-coerce contract.
        sentinel = object()
        fake_model.objects.get.return_value = sentinel
        oid = bson.ObjectId()

        result = fake_model.get(oid)

        assert result is sentinel
        # ``is`` (identity), not ==, because a re-coercion would build
        # a new ObjectId with the same hex but a different object.
        assert fake_model.objects.get.call_args.kwargs["id"] is oid

    def test_none_pk_reaches_objects_get(self, fake_model):
        # pk=None passes both isinstance checks and reaches
        # ``cls.objects.get(id=None)``. The downstream behavior depends
        # on mongoengine semantics; for the unit gate the contract is
        # simply "no early-return short-circuits None" — pin that the
        # query layer is actually invoked.
        fake_model.objects.get.return_value = None

        result = fake_model.get(None)

        assert result is None
        fake_model.objects.get.assert_called_once_with(id=None)

    def test_operation_failure_on_oid_dict_form_still_reraises(self, fake_model):
        # Cross-cut with dev's reraise tests: the pk-coercion ladder
        # runs BEFORE the try/except wrapping ``objects.get``, so an
        # OperationFailure that surfaces during the query must reach
        # the caller even when pk arrived via the $oid dict branch.
        fake_model.objects.get.side_effect = OperationFailure("cmd failed")
        oid = bson.ObjectId()

        with pytest.raises(OperationFailure):
            fake_model.get({"$oid": str(oid)})

    def test_connection_failure_on_objectid_form_still_reraises(self, fake_model):
        # Same shape as the previous test, with the already-ObjectId pk
        # path. Pins that the reraise contract is independent of which
        # pk branch was taken.
        fake_model.objects.get.side_effect = ConnectionFailure("server gone")

        with pytest.raises(ConnectionFailure):
            fake_model.get(bson.ObjectId())
