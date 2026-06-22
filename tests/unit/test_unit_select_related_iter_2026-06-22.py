"""Query-count regression guard for ``select_related()`` batch dereference.

PR #192 (Tier 1 of #153) documents — in ``src/autonomous/db/DIVERGENCE.md``
§"Known limitations → Reference dereference is N+1 by default — use
``select_related()``" — that reference dereferencing is N+1 by default and that
``QuerySet.select_related(max_depth=N)`` collapses it to one batched fetch per
referenced collection. There is **no source behavior change** in PR #192: the
batch API already ships. This file is the independent, committed proof of the
*query-count differential* the docs promise, so a future refactor that
re-introduces the N+1 (or breaks the per-collection batching) fails CI.

The two code paths distinguished here purely by call count:

* **Lazy / N+1** — ``ReferenceField.__get__`` / ``GenericReferenceField.__get__``
  (``fields.py``) → ``_lazy_load_ref`` → ``ref_cls._get_db().dereference(dbref)``,
  firing **once per field access**.
* **Batch / select_related** — ``BaseQuerySet.select_related(max_depth)``
  (``queryset/base.py:877``) → ``_dereference`` → ``DeReference.__call__`` →
  ``DeReference._fetch_objects`` (``dereference.py:155``), which fires
  ``collection.objects.in_bulk(refs)`` **once per referenced collection**
  (or one ``find({"_id": {"$in": refs}})`` for the generic-reference branch).

Hermetic: no Mongo/Redis. ``Document`` subclasses are constructed by the
metaclass without a live connection (connection is lazy — see
``DIVERGENCE.md`` §"Lazy connection"); the result-set documents are built with
``Document.__new__`` + a hand-set ``_data`` (a raw ``DBRef`` or a ``{_cls, _ref}``
SON, exactly the wire shapes the ORM stores), and the fetch / connection seams
are patched so call counts are observable. The seams patched are the same
methods ``DeReference._fetch_objects`` and ``_lazy_load_ref`` call on the live
path; only the network boundary is mocked.
"""

from unittest.mock import MagicMock, patch

import pytest
from bson import SON, DBRef, ObjectId

from autonomous.db import fields
from autonomous.db.dereference import DeReference
from autonomous.db.document import Document
from autonomous.db.queryset.base import BaseQuerySet


# --------------------------------------------------------------------------- #
# Hermetic model definitions. The metaclass builds these without touching a
# connection; only `.objects` / `_get_db()` / `_get_collection_name()` do, and
# every test patches those before they're hit.
# --------------------------------------------------------------------------- #
class Author(Document):
    name = fields.StringField()


class Post(Document):
    """Plain ``ReferenceField`` — stores a raw ``DBRef``."""

    author = fields.ReferenceField(Author)


class Tag(Document):
    label = fields.StringField()


class TaggedItem(Document):
    """``GenericReferenceField`` stores ``{_cls, _ref}`` — the exact wire shape
    the Layer-2 ``ReferenceAttr`` (``autoattr.py``, the field every consumer
    model actually uses) persists, since ``ReferenceAttr`` subclasses
    ``GenericReferenceField``. Covering this proves the generic / ``ReferenceAttr``
    path batches too, not just plain ``ReferenceField``.
    """

    tag = fields.GenericReferenceField()


class TwoRefs(Document):
    author = fields.ReferenceField(Author)
    tag = fields.GenericReferenceField()


def _bare(doc_cls, data):
    """A model instance with ``_data`` set directly, bypassing ``__init__``
    (which would side-load from Mongo per ``DIVERGENCE.md`` §auto_pre_init)."""
    obj = doc_cls.__new__(doc_cls)
    obj._data = data
    obj._fields = doc_cls._fields
    obj._dynamic = False
    return obj


def _post(author_id):
    return _bare(Post, {"id": ObjectId(), "author": DBRef("author", author_id)})


def _tagged(tag_id):
    ref = SON((("_cls", "Tag"), ("_ref", DBRef("tag", tag_id))))
    return _bare(TaggedItem, {"id": ObjectId(), "tag": ref})


def _resolved_authors(ids):
    out = {}
    for i in ids:
        a = _bare(Author, {"id": i, "name": "n"})
        out[i] = a
    return out


# --------------------------------------------------------------------------- #
# Baseline: lazy access is N+1 (one dereference per access).
# --------------------------------------------------------------------------- #
class TestLazyAccessIsNPlusOne:
    """Establishes the N+1 baseline the batch path is documented to fix:
    ``ReferenceField.__get__`` fires ``_get_db().dereference`` once per access.
    """

    def test_plain_reference_fires_one_dereference_per_access(self):
        N = 5
        ids = [ObjectId() for _ in range(N)]
        posts = [_post(i) for i in ids]

        fake_db = MagicMock()
        fake_db.dereference.return_value = {"_id": ObjectId(), "name": "x"}

        with patch.object(Author, "_get_db", return_value=fake_db), patch.object(
            Author, "_from_son", side_effect=lambda son, **kw: _bare(Author, dict(son))
        ):
            for p in posts:
                _ = p.author  # each access lazily loads -> one dereference

        # N accesses -> N dereferences. With the set query itself that's the
        # documented "1 + N" N+1 shape.
        assert fake_db.dereference.call_count == N

    def test_generic_reference_fires_one_dereference_per_access(self):
        N = 5
        ids = [ObjectId() for _ in range(N)]
        items = [_tagged(i) for i in ids]

        fake_db = MagicMock()
        fake_db.dereference.return_value = {"_id": ObjectId(), "label": "x"}

        with patch.object(Tag, "_get_db", return_value=fake_db), patch.object(
            Tag, "_from_son", side_effect=lambda son, **kw: _bare(Tag, dict(son))
        ):
            for it in items:
                _ = it.tag

        assert fake_db.dereference.call_count == N


# --------------------------------------------------------------------------- #
# Batch: select_related fires one fetch per collection, independent of N.
# --------------------------------------------------------------------------- #
class TestSelectRelatedBatchesOnePerCollection:
    """``DeReference._fetch_objects`` issues exactly one ``in_bulk`` (or one
    ``$in`` ``find``) per referenced collection — the count is constant in N.
    ``DeReference.__call__`` is what ``BaseQuerySet.select_related`` invokes, so
    driving it directly over the result set exercises the real batch path.
    """

    @pytest.mark.parametrize("n", [1, 4, 25])
    def test_plain_reference_one_in_bulk_regardless_of_n(self, n):
        ids = [ObjectId() for _ in range(n)]
        posts = [_post(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = _resolved_authors(ids)

        with patch.object(Author, "objects", fake_objects), patch.object(
            Author, "_get_collection_name", return_value="author"
        ):
            DeReference()(posts, max_depth=2)

        # One batched fetch for the whole set, not one per document.
        assert fake_objects.in_bulk.call_count == 1

    @pytest.mark.parametrize("n", [1, 4, 25])
    def test_generic_referenceattr_path_also_batches(self, n):
        """The ``{_cls, _ref}`` storage that ``ReferenceAttr`` (and every real
        consumer model) uses batches the same way: ``get_document("Tag")``
        resolves to a class with ``.objects``, so ``_fetch_objects`` takes the
        ``in_bulk`` branch once for the ``Tag`` collection.
        """
        ids = [ObjectId() for _ in range(n)]
        items = [_tagged(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = {
            i: _bare(Tag, {"id": i, "label": "n"}) for i in ids
        }

        with patch.object(Tag, "objects", fake_objects), patch.object(
            Tag, "_get_collection_name", return_value="tag"
        ):
            DeReference()(items, max_depth=2)

        assert fake_objects.in_bulk.call_count == 1

    def test_two_collections_one_query_each(self):
        """"One query *per collection*": a result set referencing two distinct
        collections fires exactly one batched fetch for each, not N per doc and
        not one combined.
        """
        n = 6
        author_ids = [ObjectId() for _ in range(n)]
        tag_ids = [ObjectId() for _ in range(n)]
        docs = []
        for aid, tid in zip(author_ids, tag_ids):
            ref = SON((("_cls", "Tag"), ("_ref", DBRef("tag", tid))))
            docs.append(
                _bare(
                    TwoRefs,
                    {"id": ObjectId(), "author": DBRef("author", aid), "tag": ref},
                )
            )

        fa = MagicMock()
        fa.in_bulk.return_value = _resolved_authors(author_ids)
        ft = MagicMock()
        ft.in_bulk.return_value = {i: _bare(Tag, {"id": i, "label": "n"}) for i in tag_ids}

        with patch.object(Author, "objects", fa), patch.object(
            Tag, "objects", ft
        ), patch.object(
            Author, "_get_collection_name", return_value="author"
        ), patch.object(
            Tag, "_get_collection_name", return_value="tag"
        ):
            DeReference()(docs, max_depth=2)

        assert fa.in_bulk.call_count == 1
        assert ft.in_bulk.call_count == 1


# --------------------------------------------------------------------------- #
# The payoff: after the batch stitch, per-access dereference is zero.
# --------------------------------------------------------------------------- #
class TestBatchEliminatesPerAccessDereference:
    """The actual N+1 elimination: after ``select_related`` stitches resolved
    documents into ``_data``, reading the reference on each element triggers
    **zero** lazy ``dereference`` calls — the documented win, asserted as a
    count differential against :class:`TestLazyAccessIsNPlusOne`.
    """

    def test_zero_lazy_dereference_after_batch_plain_reference(self):
        N = 4
        ids = [ObjectId() for _ in range(N)]
        posts = [_post(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = _resolved_authors(ids)
        fake_db = MagicMock()  # would record any lazy dereference

        with patch.object(Author, "objects", fake_objects), patch.object(
            Author, "_get_collection_name", return_value="author"
        ), patch.object(Author, "_get_db", return_value=fake_db):
            out = DeReference()(posts, max_depth=2)

            # _data["author"] is now a resolved Author, not a DBRef.
            assert all(isinstance(p._data["author"], Author) for p in out)

            for p in out:
                _ = p.author  # already cached -> no lazy load

            assert fake_db.dereference.call_count == 0

    def test_zero_lazy_dereference_after_batch_generic_reference(self):
        N = 4
        ids = [ObjectId() for _ in range(N)]
        items = [_tagged(i) for i in ids]

        fake_objects = MagicMock()
        fake_objects.in_bulk.return_value = {
            i: _bare(Tag, {"id": i, "label": "n"}) for i in ids
        }
        fake_db = MagicMock()

        with patch.object(Tag, "objects", fake_objects), patch.object(
            Tag, "_get_collection_name", return_value="tag"
        ), patch.object(Tag, "_get_db", return_value=fake_db):
            out = DeReference()(items, max_depth=2)

            assert all(isinstance(it._data["tag"], Tag) for it in out)

            for it in out:
                _ = it.tag

            assert fake_db.dereference.call_count == 0


# --------------------------------------------------------------------------- #
# The public entrypoint routes through the batch path with the documented
# depth semantics.
# --------------------------------------------------------------------------- #
class TestSelectRelatedEntrypoint:
    """``BaseQuerySet.select_related`` is the documented public API. Confirm it
    clones, bumps ``max_depth`` by one (so ``select_related(1)`` resolves the
    direct references — see ``DIVERGENCE.md`` "max_depth controls nested-reference
    depth"), and delegates to the batch ``_dereference`` machinery.
    """

    def test_select_related_delegates_to_dereference_with_bumped_depth(self):
        qs = BaseQuerySet.__new__(BaseQuerySet)
        fake_deref = MagicMock(return_value=["batched-result"])

        with patch.object(BaseQuerySet, "clone", return_value=qs), patch.object(
            type(qs), "_dereference", new_callable=lambda: property(lambda self: fake_deref)
        ):
            out = qs.select_related(max_depth=1)

        assert out == ["batched-result"]
        # select_related(1) -> _dereference(..., max_depth=2): the +1 makes the
        # user-facing depth resolve the direct references on each result.
        _, kwargs = fake_deref.call_args
        assert kwargs.get("max_depth") == 2
