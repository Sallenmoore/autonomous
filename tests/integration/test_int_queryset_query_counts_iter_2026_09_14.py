"""Query-count guards for queryset materialization (#260, pinning #250).

Issue #260 reported that iterating a queryset cost ~1 Mongo round trip per
document *including* ``.only()`` / ``values_list()`` projections. Measured
here at N = 1, 10, 100, that is false on this code: every materialization
path is FLAT at one query. The reported numbers were taken against 0.3.177,
hours before #250 shipped in 0.3.178 and removed the per-construction
``find_one`` in ``AutoModel.auto_pre_init``.

#250's own unit tests pin the *hook* (it returns early for ``created=False``).
These pin the *property a consumer actually cares about*: materializing N
documents does not cost N queries, measured end-to-end through pymongo's
command listener rather than by asserting on internals. A regression in any
layer between the queryset and the driver fails these, including one that
does not touch the hook at all.

Also pinned: reference access is lazily dereferenced per document (intended
mongoengine semantics, NOT the #250 defect), and the documented
``_select_related`` opt-in collapses that to a single batched query.
"""

from collections import Counter

import pytest
from pymongo import monitoring

from autonomous.model import automodel
from autonomous.model.autoattr import ListAttr, ReferenceAttr, StringAttr
from autonomous.model.automodel import AutoModel

pytestmark = pytest.mark.integration


class QueryCountTarget(AutoModel):
    name = StringAttr(default="")


class QueryCountDoc(AutoModel):
    name = StringAttr(default="")
    # ReferenceAttr is a GenericReferenceField ({_cls, _ref}) — the shape #260
    # fingered as the trigger.
    owner = ReferenceAttr()
    friends = ListAttr(ReferenceAttr())


class _ReadCounter(monitoring.CommandListener):
    """Counts read commands issued to Mongo, driver-side.

    Registered process-wide (pymongo has no unregister), so it is inert until
    a test opens a ``counting`` block.
    """

    def __init__(self):
        self.counts = Counter()
        self.active = False

    def started(self, event):
        if self.active and event.command_name in ("find", "getMore", "aggregate"):
            self.counts[event.command_name] += 1

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


_COUNTER = _ReadCounter()
monitoring.register(_COUNTER)


class _Counting:
    """A measured block. ``total`` is SNAPSHOT on exit, never live.

    A live property over the shared counter would make two blocks in one test
    compare equal: the second block's ``clear()`` would wipe the first block's
    result before the assertion read it, and a real N+1 would report as flat.
    """

    def __init__(self):
        self._total = None

    def __enter__(self):
        _COUNTER.counts.clear()
        _COUNTER.active = True
        return self

    def __exit__(self, *exc):
        self._total = sum(_COUNTER.counts.values())
        _COUNTER.active = False
        return False

    @property
    def total(self):
        # Inside the block, report live; afterwards, the frozen snapshot.
        if self._total is None:
            return sum(_COUNTER.counts.values())
        return self._total


def counting():
    return _Counting()


@pytest.fixture
def seeded():
    """Yields a seeding callable; cleans up both collections afterwards."""

    # Connection is lazy and opens on the first ORM *operation*; the raw
    # ``objects()`` manager below does not trigger it.
    automodel._ensure_connected()

    def _seed(n):
        QueryCountDoc.objects().delete()
        QueryCountTarget.objects().delete()
        targets = []
        for i in range(3):
            t = QueryCountTarget(name=f"t{i}")
            t.save()
            targets.append(t)
        for i in range(n):
            QueryCountDoc(
                name=f"d{i}", owner=targets[i % 3], friends=list(targets)
            ).save()
        return targets

    yield _seed
    QueryCountDoc.objects().delete()
    QueryCountTarget.objects().delete()


# Chosen so a per-document regression is unmistakable: an N+1 at N=25 reads
# 26 where the guard allows 2. Small enough to stay fast on the CI stack.
BULK_N = 25


class TestMaterializationDoesNotScaleWithRowCount:
    """The #260 claim, measured. Each of these was ~N+1 before #250."""

    @pytest.mark.parametrize(
        "label,build",
        [
            ("objects()", lambda: list(QueryCountDoc.objects())),
            ("only('pk')", lambda: list(QueryCountDoc.objects().only("pk"))),
            ("values_list('pk')", lambda: list(QueryCountDoc.objects().values_list("pk"))),
            ("no_dereference()", lambda: list(QueryCountDoc.objects().no_dereference())),
            ("all()", lambda: QueryCountDoc.all()),
        ],
    )
    def test_path_is_flat_in_row_count(self, seeded, label, build):
        seeded(BULK_N)
        with counting() as c:
            rows = build()
        assert len(rows) == BULK_N, f"{label} returned {len(rows)} rows"
        assert c.total <= 2, (
            f"{label} issued {c.total} queries for {BULK_N} rows — a per-document "
            f"round trip is back (#260/#250)"
        )

    def test_cost_does_not_grow_between_two_row_counts(self, seeded):
        # Scale-invariance stated directly: 10x the rows must not cost more
        # queries. Catches a regression even if someone raises the constant
        # in the guard above.
        seeded(3)
        with counting() as small:
            assert len(list(QueryCountDoc.objects())) == 3
        seeded(30)
        with counting() as large:
            assert len(list(QueryCountDoc.objects())) == 30
        assert large.total <= small.total, (
            f"materializing 30 rows cost {large.total} queries vs {small.total} "
            f"for 3 — cost scales with row count (#260)"
        )

    def test_get_by_pk_is_a_single_query(self, seeded):
        seeded(1)
        pk = QueryCountDoc.objects().first().pk
        with counting() as c:
            doc = QueryCountDoc.get(pk)
        assert doc is not None
        assert c.total == 1, f"get(pk) issued {c.total} queries, expected 1 (#250)"


class TestReferenceDereferenceIsLazyAndBatchable:
    """The residual per-document cost #260 actually measured.

    This is intended mongoengine laziness, not the #250 defect — so it is
    pinned as expected behavior, with the documented escape hatch pinned
    beside it. If someone makes dereference eager to "fix" #260, the first
    test fails and says why.
    """

    def test_untouched_references_cost_nothing(self, seeded):
        seeded(BULK_N)
        with counting() as c:
            docs = list(QueryCountDoc.objects())
            _ = [d.name for d in docs]  # non-reference field: no I/O
        assert c.total <= 2, (
            f"reading only non-reference fields issued {c.total} queries; "
            f"dereference should stay lazy"
        )

    def test_select_related_collapses_reference_access_to_one_batch(self, seeded):
        seeded(BULK_N)
        with counting() as c:
            docs = QueryCountDoc.all(_select_related=True)
            owners = [d.owner for d in docs]
        after = c.total
        assert len(docs) == BULK_N
        assert all(o is not None for o in owners)
        assert after <= 3, (
            f"_select_related=True issued {after} queries for {BULK_N} rows plus "
            f"their references — the batch dereference is not batching (#153/#195)"
        )

    def test_select_related_beats_lazy_access_at_scale(self, seeded):
        # Relative claim, immune to constant drift: the opt-in must be
        # cheaper than lazy access once there are many rows to dereference.
        seeded(BULK_N)
        with counting() as lazy:
            _ = [d.owner for d in QueryCountDoc.objects()]
        seeded(BULK_N)
        with counting() as batched:
            _ = [d.owner for d in QueryCountDoc.all(_select_related=True)]
        assert batched.total < lazy.total, (
            f"_select_related ({batched.total} queries) is not cheaper than lazy "
            f"access ({lazy.total}) for {BULK_N} rows"
        )
