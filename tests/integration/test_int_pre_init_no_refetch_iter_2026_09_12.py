"""Live measurement for PR #253 (closes #250) against the Compose Mongo.

Materializing N saved documents issues ZERO ``find_one`` refetches (it was
N — one per ``pre_init``), while a bare-pk construction still hydrates
with exactly one. ``find_one`` is counted at the pymongo ``Collection``
level: the query path itself uses ``find`` cursors, so every ``find_one``
seen here is the hook's side-load and nothing else.
"""

import pytest
from pymongo.collection import Collection

from autonomous.model import automodel
from autonomous.model.autoattr import StringAttr
from autonomous.model.automodel import AutoModel

N = 5


class _Materialized(AutoModel):
    name = StringAttr(default="")
    note = StringAttr(default="")


@pytest.fixture
def saved():
    automodel._ensure_connected()
    _Materialized.drop_collection()
    docs = []
    for i in range(N):
        doc = _Materialized(name=f"n{i}", note="stored")
        doc.save()
        docs.append(doc)
    yield docs
    _Materialized.drop_collection()


@pytest.fixture
def find_one_calls(monkeypatch):
    calls = []
    real = Collection.find_one

    def spy(self, *args, **kwargs):
        calls.append(args)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Collection, "find_one", spy)
    return calls


def test_query_materialization_issues_no_refetch(saved, find_one_calls):
    got = list(_Materialized.objects(pk__in=[d.pk for d in saved]))
    assert len(got) == N
    assert {d.note for d in got} == {"stored"}
    assert find_one_calls == []


def test_all_and_get_issue_no_refetch(saved, find_one_calls):
    assert len(_Materialized.all()) == N
    assert _Materialized.get(saved[0].pk).name == "n0"
    assert find_one_calls == []


def test_reload_issues_no_refetch(saved, find_one_calls):
    saved[0].reload()
    assert find_one_calls == []


def test_bare_pk_construction_still_hydrates_once(saved, find_one_calls):
    doc = _Materialized(pk=saved[0].pk)
    assert doc.name == "n0"
    assert doc.note == "stored"
    assert len(find_one_calls) == 1
