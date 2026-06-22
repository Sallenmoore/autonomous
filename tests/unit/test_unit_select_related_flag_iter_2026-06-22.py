"""Independent committed proof of the ``_select_related`` flag on
``AutoModel.all()`` / ``AutoModel.search()`` (PR #196 / issue #195).

PR #196 adds an opt-in, default-off control argument
``_select_related: bool | int = False`` to ``AutoModel.all()`` and
``AutoModel.search()`` (``src/autonomous/model/automodel.py``). It is routed
through a new module-level helper ``_maybe_select_related(qs, flag)`` →
``qs.select_related(max_depth=...)``:

* falsy (``False`` / ``0`` / ``None``, the default) → off, ``select_related``
  is **not** called and the queryset is returned unchanged;
* ``True`` → ``max_depth=1``; int ``N`` (≥ 1) → ``max_depth=N``;
* negative (truthy) int → ``ValueError``; non-bool/non-int → ``TypeError``.

In ``search()`` the flag is applied **after** ``_order_by`` / ``_limit``, so
only the rows actually returned are batch-dereferenced.

This file is written from the PR diff + a fresh perspective (the second of the
two-perspective testing discipline — it does NOT consult dev's
``tests/_dev_local/``). It proves the documented behavior at three levels:

1. **Helper level** — spy on a ``MagicMock`` queryset's ``.select_related`` to
   pin the flag → ``max_depth`` mapping, the default-off no-call, and the
   ``ValueError`` / ``TypeError`` validation.
2. **Routing level** — drive the real ``all()`` / ``search()`` classmethod
   *functions* with a stand-in ``cls`` whose ``.objects()`` returns a stub
   queryset (mongoengine's ``objects`` descriptor resists monkeypatching on a
   real subclass, so a stand-in cls is cleaner), spying on
   ``_maybe_select_related`` to assert the flag is forwarded and — for
   ``search()`` — that the helper sees the **post-``_limit``** queryset.
3. **Query-count batch-vs-N+1** — the end-to-end payoff, reusing the proven
   hermetic ``DeReference`` pattern from
   ``tests/unit/test_unit_select_related_iter_2026-06-22.py`` (the #153 Tier-1
   test): default-off keeps one lazy ``dereference`` per access (the N+1);
   ``select_related`` collapses it to one ``in_bulk`` per referenced collection
   plus **zero** per-access ``dereference`` afterwards — for both plain
   ``ReferenceField`` (raw ``DBRef``) and the generic ``{_cls, _ref}`` /
   ``ReferenceAttr`` wire shape every real consumer model uses.

Hermetic: no Mongo / Redis. ``Document`` subclasses are built by the metaclass
without a connection (connection is lazy); result-set documents use
``Document.__new__`` + a hand-set ``_data``; the fetch / connection seams are
patched so call counts are observable.
"""

from unittest.mock import MagicMock, patch

import pytest
from bson import SON, DBRef, ObjectId

import autonomous.model.automodel as am
from autonomous.db import fields
from autonomous.db.dereference import DeReference
from autonomous.db.document import Document
from autonomous.model.automodel import _maybe_select_related


# --------------------------------------------------------------------------- #
# 1. Helper level: _maybe_select_related(qs, flag) → qs.select_related(...)
# --------------------------------------------------------------------------- #
class TestMaybeSelectRelatedHelper:
    """The flag → ``max_depth`` translation, default-off, and validation, with
    ``select_related`` spied on a ``MagicMock`` queryset (no DB)."""

    @pytest.mark.parametrize("off", [False, 0, None])
    def test_falsy_is_off_returns_qs_unchanged_no_call(self, off):
        """Default / falsy never touches ``select_related`` and returns the
        SAME queryset object — the byte-identical-to-before guarantee."""
        qs = MagicMock(name="qs")
        out = _maybe_select_related(qs, off)
        assert out is qs
        qs.select_related.assert_not_called()

    def test_true_maps_to_depth_1(self):
        qs = MagicMock(name="qs")
        out = _maybe_select_related(qs, True)
        qs.select_related.assert_called_once_with(max_depth=1)
        # the helper returns the select_related result, not the raw qs
        assert out is qs.select_related.return_value

    @pytest.mark.parametrize("n", [1, 2, 3, 7])
    def test_positive_int_maps_to_that_depth(self, n):
        qs = MagicMock(name="qs")
        _maybe_select_related(qs, n)
        qs.select_related.assert_called_once_with(max_depth=n)

    def test_depth_3_maps_through(self):
        """Explicit coverage of the documented ``_select_related=3`` →
        ``select_related(max_depth=3)`` case."""
        qs = MagicMock(name="qs")
        _maybe_select_related(qs, 3)
        qs.select_related.assert_called_once_with(max_depth=3)

    @pytest.mark.parametrize("bad", [-1, -5, -100])
    def test_negative_int_raises_value_error(self, bad):
        qs = MagicMock(name="qs")
        with pytest.raises(ValueError):
            _maybe_select_related(qs, bad)
        qs.select_related.assert_not_called()

    @pytest.mark.parametrize("bad", ["2", 2.0, [1], (1,), {"d": 1}])
    def test_non_bool_non_int_raises_type_error(self, bad):
        qs = MagicMock(name="qs")
        with pytest.raises(TypeError):
            _maybe_select_related(qs, bad)
        qs.select_related.assert_not_called()


# --------------------------------------------------------------------------- #
# Stand-in cls plumbing for the routing-level tests. We call the real
# classmethod *function* (``.all.__func__`` / ``.search.__func__``) with a
# hand-rolled cls so ``cls.objects(...)`` returns our stub without mongoengine's
# ``objects`` descriptor or a live connection getting in the way.
# --------------------------------------------------------------------------- #
class _FakeQS:
    """Minimal chainable queryset stub. ``order_by`` returns self; slicing
    returns a DISTINCT sentinel so the ordering assertion can tell the raw
    queryset apart from the post-``_limit`` one. Records the kwargs ``objects``
    was last called with so ``search()``'s field-filter translation is visible.
    """

    def __init__(self):
        self.order_by_args = None
        self.slice_keys = []
        self.LIMITED = "LIMITED_QS"

    def order_by(self, *args):
        self.order_by_args = args
        return self

    def __getitem__(self, key):
        self.slice_keys.append(key)
        return self.LIMITED


class _FakeCls:
    """Stand-in for an ``AutoModel`` subclass. ``objects`` is a plain callable,
    so ``cls.objects(**kw)`` returns our stub — no descriptor, no DB."""

    def __init__(self, qs):
        self._qs = qs
        self.objects_calls = []

    def objects(self, **kwargs):
        self.objects_calls.append(kwargs)
        return self._qs


def _spy_helper(monkeypatch):
    """Replace ``_maybe_select_related`` with a spy that records the queryset
    and flag it was handed, and returns ``[]`` so ``list(...)`` is cheap."""
    captured = {}

    def spy(qs, flag):
        captured["qs"] = qs
        captured["flag"] = flag
        captured.setdefault("calls", 0)
        captured["calls"] += 1
        return []

    monkeypatch.setattr(am, "_ensure_connected", lambda: None)
    monkeypatch.setattr(am, "_maybe_select_related", spy)
    return captured


# --------------------------------------------------------------------------- #
# 2a. all() routing
# --------------------------------------------------------------------------- #
class TestAllRoutesFlag:
    def test_all_default_passes_falsy_flag_and_raw_objects(self, monkeypatch):
        cap = _spy_helper(monkeypatch)
        qs = _FakeQS()
        cls = _FakeCls(qs)

        out = am.AutoModel.all.__func__(cls)

        assert out == []
        assert cap["flag"] is False           # default off
        assert cap["qs"] is qs                 # cls.objects() handed straight through
        assert cls.objects_calls == [{}]       # all() filters on nothing

    def test_all_forwards_true(self, monkeypatch):
        cap = _spy_helper(monkeypatch)
        cls = _FakeCls(_FakeQS())
        am.AutoModel.all.__func__(cls, _select_related=True)
        assert cap["flag"] is True

    @pytest.mark.parametrize("depth", [1, 2, 5])
    def test_all_forwards_depth_value(self, monkeypatch, depth):
        cap = _spy_helper(monkeypatch)
        cls = _FakeCls(_FakeQS())
        am.AutoModel.all.__func__(cls, _select_related=depth)
        assert cap["flag"] == depth


# --------------------------------------------------------------------------- #
# 2b. search() routing — flag applied AFTER _order_by / _limit
# --------------------------------------------------------------------------- #
class TestSearchRoutesFlag:
    def test_search_default_off(self, monkeypatch):
        cap = _spy_helper(monkeypatch)
        cls = _FakeCls(_FakeQS())
        am.AutoModel.search.__func__(cls, name="x")
        assert cap["flag"] is False

    @pytest.mark.parametrize("depth", [True, 2, 4])
    def test_search_forwards_flag_value(self, monkeypatch, depth):
        cap = _spy_helper(monkeypatch)
        cls = _FakeCls(_FakeQS())
        am.AutoModel.search.__func__(cls, name="x", _select_related=depth)
        assert cap["flag"] == depth

    def test_search_string_filter_becomes_icontains(self, monkeypatch):
        """Sanity: the flag plumbing doesn't disturb the existing string →
        ``__icontains`` translation (non-strings stay exact)."""
        _spy_helper(monkeypatch)
        qs = _FakeQS()
        cls = _FakeCls(qs)
        am.AutoModel.search.__func__(cls, name="alice", age=30, _select_related=True)
        assert cls.objects_calls == [{"name__icontains": "alice", "age": 30}]

    def test_search_applies_flag_after_limit(self, monkeypatch):
        """The queryset handed to the helper must be the POST-slice sentinel,
        not the raw queryset — proving the flag is applied after ``_limit`` so
        only the limited rows are batch-fetched."""
        cap = _spy_helper(monkeypatch)
        qs = _FakeQS()
        cls = _FakeCls(qs)
        am.AutoModel.search.__func__(cls, name="x", _limit=5, _select_related=True)
        assert cap["qs"] == qs.LIMITED           # the [:5] result, not qs
        assert qs.slice_keys == [slice(None, 5)]  # _limit=5 → results[:5]

    def test_search_applies_flag_after_limit_pair(self, monkeypatch):
        """``_limit=[start, end]`` slices ``results[start:end]`` and the helper
        still sees that post-slice queryset."""
        cap = _spy_helper(monkeypatch)
        qs = _FakeQS()
        cls = _FakeCls(qs)
        am.AutoModel.search.__func__(
            cls, name="x", _limit=[2, 8], _select_related=2
        )
        assert cap["qs"] == qs.LIMITED
        assert qs.slice_keys == [slice(2, 8)]
        assert cap["flag"] == 2

    def test_search_applies_flag_after_order_by(self, monkeypatch):
        """With ``_order_by`` and no ``_limit`` the helper sees the ordered
        queryset (``order_by`` returns the same stub), and ordering was applied
        before the flag — i.e. the flag is genuinely last in the chain."""
        cap = _spy_helper(monkeypatch)
        qs = _FakeQS()
        cls = _FakeCls(qs)
        am.AutoModel.search.__func__(
            cls, name="x", _order_by=("name",), _select_related=True
        )
        assert qs.order_by_args == ("name",)
        assert cap["qs"] is qs                 # no slice → ordered qs handed on


# --------------------------------------------------------------------------- #
# 3. Query-count batch-vs-N+1 — the end-to-end payoff over the real
# DeReference path (the same hermetic seams the #153 Tier-1 test uses).
#
# NOTE on class names: the ODM keeps a GLOBAL document registry keyed by class
# name (``autonomous.db.base.common._document_registry``), and the generic
# ``{_cls, _ref}`` path resolves the target via ``get_document(_cls)`` — a
# by-name lookup. The sibling #153 test file
# (``test_unit_select_related_iter_2026-06-22.py``) defines ``Author`` / ``Tag``
# / ``Post`` too, so plain names would collide in the registry and
# ``get_document("Tag")`` could resolve to the OTHER file's (unpatched) class
# when both files load — a cross-file ordering failure. The ``Flag195`` suffix
# keeps these names unique so ``_cls`` resolves back to the class this file
# patches.
# --------------------------------------------------------------------------- #
class AuthorFlag195(Document):
    name = fields.StringField()


class PostFlag195(Document):
    """Plain ``ReferenceField`` — stores a raw ``DBRef``."""

    author = fields.ReferenceField(AuthorFlag195)


class TagFlag195(Document):
    label = fields.StringField()


class TaggedItemFlag195(Document):
    """``GenericReferenceField`` stores ``{_cls, _ref}`` — the exact wire shape
    the Layer-2 ``ReferenceAttr`` (the field every real consumer model uses)
    persists, since ``ReferenceAttr`` subclasses ``GenericReferenceField``.
    """

    tag = fields.GenericReferenceField()


def _bare(doc_cls, data):
    """A model instance with ``_data`` set directly, bypassing ``__init__``
    (which would side-load from Mongo)."""
    obj = doc_cls.__new__(doc_cls)
    obj._data = data
    obj._fields = doc_cls._fields
    obj._dynamic = False
    return obj


def _post(author_id):
    return _bare(
        PostFlag195, {"id": ObjectId(), "author": DBRef("author", author_id)}
    )


def _tagged(tag_id):
    # _cls must name THIS file's registered class so get_document() resolves it.
    ref = SON((("_cls", "TagFlag195"), ("_ref", DBRef("tag", tag_id))))
    return _bare(TaggedItemFlag195, {"id": ObjectId(), "tag": ref})


def _resolved_authors(ids):
    return {i: _bare(AuthorFlag195, {"id": i, "name": "n"}) for i in ids}


class TestDefaultOffStaysNPlusOne:
    """Default-off (the helper returns the queryset unchanged): iterating and
    reading the reference per element fires one lazy ``dereference`` per access
    — the classic N+1 the flag exists to fix. This is the baseline the
    ``_select_related=True`` cases below collapse."""

    def test_plain_reference_off_is_one_dereference_per_access(self):
        N = 5
        ids = [ObjectId() for _ in range(N)]
        posts = [_post(i) for i in ids]

        # default-off path: the helper hands the raw result set straight back,
        # so the documents are still un-stitched DBRefs.
        result = _maybe_select_related(posts, False)
        assert result is posts

        fake_db = MagicMock()
        fake_db.dereference.return_value = {"_id": ObjectId(), "name": "x"}
        with patch.object(
            AuthorFlag195, "_get_db", return_value=fake_db
        ), patch.object(
            AuthorFlag195,
            "_from_son",
            side_effect=lambda son, **kw: _bare(AuthorFlag195, dict(son)),
        ):
            for p in result:
                _ = p.author  # each access lazily loads → one dereference

        assert fake_db.dereference.call_count == N  # the N in 1 + N

    def test_generic_reference_off_is_one_dereference_per_access(self):
        N = 5
        ids = [ObjectId() for _ in range(N)]
        items = [_tagged(i) for i in ids]

        result = _maybe_select_related(items, 0)  # falsy int → off
        assert result is items

        fake_db = MagicMock()
        fake_db.dereference.return_value = {"_id": ObjectId(), "label": "x"}
        with patch.object(
            TagFlag195, "_get_db", return_value=fake_db
        ), patch.object(
            TagFlag195,
            "_from_son",
            side_effect=lambda son, **kw: _bare(TagFlag195, dict(son)),
        ):
            for it in items:
                _ = it.tag

        assert fake_db.dereference.call_count == N


class TestSelectRelatedTrueBatches:
    """With the flag on, the real ``select_related`` path (driven through
    ``DeReference`` exactly as ``BaseQuerySet.select_related`` invokes it) fires
    exactly ONE ``in_bulk`` per referenced collection regardless of N, and
    reading the reference per element afterwards triggers ZERO lazy
    ``dereference`` — proving the N+1 is gone for both reference shapes."""

    @pytest.mark.parametrize("n", [1, 4, 25])
    def test_plain_reference_one_in_bulk_then_zero_lazy(self, n):
        ids = [ObjectId() for _ in range(n)]
        posts = [_post(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = _resolved_authors(ids)
        fake_db = MagicMock()  # would record any lazy dereference

        with patch.object(AuthorFlag195, "objects", fake_objects), patch.object(
            AuthorFlag195, "_get_collection_name", return_value="author"
        ), patch.object(AuthorFlag195, "_get_db", return_value=fake_db):
            out = DeReference()(posts, max_depth=2)

            assert fake_objects.in_bulk.call_count == 1     # one batched fetch
            assert all(isinstance(p._data["author"], AuthorFlag195) for p in out)
            for p in out:
                _ = p.author                                 # already stitched
            assert fake_db.dereference.call_count == 0       # no lazy loads

    @pytest.mark.parametrize("n", [1, 4, 25])
    def test_generic_referenceattr_one_in_bulk_then_zero_lazy(self, n):
        """The ``{_cls, _ref}`` storage ``ReferenceAttr`` uses batches the same
        way: one ``in_bulk`` for the ``Tag`` collection, then zero lazy loads."""
        ids = [ObjectId() for _ in range(n)]
        items = [_tagged(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = {
            i: _bare(TagFlag195, {"id": i, "label": "n"}) for i in ids
        }
        fake_db = MagicMock()

        with patch.object(TagFlag195, "objects", fake_objects), patch.object(
            TagFlag195, "_get_collection_name", return_value="tag"
        ), patch.object(TagFlag195, "_get_db", return_value=fake_db):
            out = DeReference()(items, max_depth=2)

            assert fake_objects.in_bulk.call_count == 1
            assert all(isinstance(it._data["tag"], TagFlag195) for it in out)
            for it in out:
                _ = it.tag
            assert fake_db.dereference.call_count == 0


class TestFlagDrivesBatchPathDepth:
    """End-to-end through the helper: ``_maybe_select_related(qs, flag)`` calls
    ``qs.select_related(max_depth=flag)``, so the documented depth maps straight
    onto the queryset API. (The internal ``max_depth += 1`` bump inside
    ``BaseQuerySet.select_related`` is covered by the #153 Tier-1 test; here we
    pin the user-facing-flag → ``max_depth`` contract the new code owns.)"""

    @pytest.mark.parametrize(
        "flag, expected_depth", [(True, 1), (1, 1), (2, 2), (3, 3), (5, 5)]
    )
    def test_flag_maps_to_select_related_max_depth(self, flag, expected_depth):
        qs = MagicMock(name="qs")
        _maybe_select_related(qs, flag)
        qs.select_related.assert_called_once_with(max_depth=expected_depth)


class TestSearchLimitThenBatchSeesLimitedSet:
    """``search()`` applies the flag after ``_limit``, so the batched fetch only
    ever sees the limited id set. Driven through the real ``search`` function
    with a stub queryset whose slice yields a small post-limit result that is
    then handed to the REAL helper → real ``select_related``; the spy on the
    sliced queryset's ``select_related`` records the post-limit object."""

    def test_only_limited_rows_reach_select_related(self, monkeypatch):
        monkeypatch.setattr(am, "_ensure_connected", lambda: None)

        # post-limit queryset is a MagicMock so we can see select_related on IT.
        limited = MagicMock(name="limited_qs")

        class _QS:
            def __getitem__(self, key):
                assert key == slice(None, 3)     # _limit=3 → results[:3]
                return limited

        class _Cls:
            def objects(self, **kw):
                return _QS()

        # use the REAL _maybe_select_related (not the spy) so the helper's
        # select_related call lands on the post-limit object.
        am.AutoModel.search.__func__(
            _Cls(), name="x", _limit=3, _select_related=True
        )
        limited.select_related.assert_called_once_with(max_depth=1)
