"""Independent test-agent coverage for PR #270 / #269 — the lore index
text built by ``db_sync.process_single_object_sync``.

New contract (from the PR diff):
- hash ``content`` (and the embedder input) is
  ``"{name}: {digest}\\nRelated: {names}\\n{history}"``;
- digest = ``desc_summary`` (else ``desc``/``description`` cut to 400
  chars), then ``backstory_summary``; GM-only fields are never read;
- every part is HTML-stripped and whitespace-collapsed (``_plain``);
- ``Related:`` lists entity **names**, resolved with one ``$in`` find per
  DBRef collection, order kept, first 20 associations only, with None /
  dangling refs / bare ObjectIds skipped and plain strings kept;
- the ``MIN_CONTENT_CHARS`` gate counts name + digest + history + names.

Mongo is a tiny in-memory fake (not MagicMock) so the ``$in`` filter and
projection are actually evaluated.
"""

import sys

import pytest
from bson.dbref import DBRef
from bson.objectid import ObjectId

from autonomous.db import db_sync


class _FakeColl:
    def __init__(self, rows):
        self.rows = {r["_id"]: r for r in rows}
        self.find_calls = []

    def find_one(self, query, projection=None):
        return self.rows.get(query["_id"])

    def find(self, query, projection=None):
        self.find_calls.append((query, projection))
        ids = query["_id"]["$in"]
        return [
            {k: v for k, v in self.rows[i].items() if k in ("_id", "name")}
            for i in ids if i in self.rows
        ]


class _FakeDb(dict):
    def __missing__(self, name):
        self[name] = _FakeColl([])
        return self[name]


class _StubNumpy:
    float32 = object

    @staticmethod
    def array(values, dtype=None):
        return type("A", (), {"tobytes": lambda self: b"v"})()


@pytest.fixture
def sync(monkeypatch):
    """Returns (db, run). ``run(doc)`` stores ``doc`` in ``lore`` and
    runs the worker; it returns the hash mapping written, or None if
    the doc was skipped. ``run.vector_inputs`` records embedder input."""
    db = _FakeDb()
    written = []
    vector_inputs = []

    class _Redis:
        def get(self, _):
            return "tok"

        def hset(self, key, mapping):
            written.append(mapping)

    monkeypatch.setitem(sys.modules, "numpy", _StubNumpy())
    monkeypatch.setattr(db_sync, "_get_redis", _Redis)
    monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: db)
    monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
    monkeypatch.setattr(db_sync, "record_embedding_sync_event", lambda *_: None)
    monkeypatch.setattr(
        db_sync, "get_vector", lambda text: vector_inputs.append(text) or [0.1]
    )

    def run(doc):
        doc.setdefault("_id", "lore_x")
        db["lore"] = _FakeColl([doc])
        written.clear()
        db_sync.process_single_object_sync(doc["_id"], "lore", "tok")
        return written[0] if written else None

    run.vector_inputs = vector_inputs
    return db, run


def _ref(coll, oid, son=True):
    ref = DBRef(coll, oid)
    return {"_cls": coll.title(), "_ref": ref} if son else ref


# ---------------------------------------------------------------------------
# Text layout
# ---------------------------------------------------------------------------


def test_layout_is_name_digest_related_history(sync):
    db, run = sync
    a, b = ObjectId(), ObjectId()
    db["character"] = _FakeColl([{"_id": a, "name": "Ayla"}])
    db["place"] = _FakeColl([{"_id": b, "name": "Brindle Keep"}])
    mapping = run({
        "name": "Mira",
        "desc_summary": "A smuggler queen.",
        "backstory_summary": "Born in the docks.",
        "history": "Long history text.",
        "associations": [_ref("character", a), _ref("place", b, son=False)],
    })
    expected = (
        "Mira: A smuggler queen. Born in the docks.\n"
        "Related: Ayla, Brindle Keep\n"
        "Long history text."
    )
    assert mapping["content"] == expected
    assert run.vector_inputs == [expected]


def test_desc_summary_preferred_over_desc(sync):
    _, run = sync
    content = run({"name": "N", "desc_summary": "short summary", "desc": "LONG DESC"})["content"]
    assert content.startswith("N: short summary\n")
    assert "LONG DESC" not in content


@pytest.mark.parametrize("field", ["desc", "description"])
def test_desc_fallback_truncated_to_400(sync, field):
    _, run = sync
    content = run({"name": "N", field: "x" * 450 + "TAIL"})["content"]
    assert content == "N: " + "x" * 400 + "\nRelated: \n"


def test_empty_digest_and_related_still_well_formed(sync):
    _, run = sync
    assert run({"name": "Plain", "history": "Some history."})["content"] == (
        "Plain: \nRelated: \nSome history."
    )


def test_html_stripped_and_entities_unescaped(sync):
    _, run = sync
    content = run({
        "name": "<b>Mira</b>",
        "desc_summary": "<p>Fish &amp; chips</p>\n\n<p>  twice  </p>",
        "history": "<div><h2>Era</h2><p>the  war</p></div>",
    })["content"]
    assert content == "Mira: Fish & chips twice\nRelated: \nEra the war"


def test_gm_only_fields_never_leak(sync):
    _, run = sync
    content = run({
        "name": "Mira",
        "desc_summary": "public",
        "secrets": "SECRET-PLOT",
        "gm_notes": "GM-NOTE",
        "history": "h" * 20,
    })["content"]
    assert "SECRET-PLOT" not in content
    assert "GM-NOTE" not in content


# ---------------------------------------------------------------------------
# Association name resolution
# ---------------------------------------------------------------------------


def test_names_resolved_one_in_query_per_collection_order_kept(sync):
    db, run = sync
    c1, c2, p1 = ObjectId(), ObjectId(), ObjectId()
    db["character"] = _FakeColl([
        {"_id": c1, "name": "C-one", "secrets": "S"},
        {"_id": c2, "name": "C-two"},
    ])
    db["place"] = _FakeColl([{"_id": p1, "name": "P-one"}])
    content = run({
        "name": "Mira",
        "associations": [
            _ref("character", c2), _ref("place", p1), _ref("character", c1),
        ],
    })["content"]
    assert "\nRelated: C-two, P-one, C-one\n" in content
    assert db["character"].find_calls == [
        ({"_id": {"$in": [c2, c1]}}, {"name": 1})
    ]
    assert len(db["place"].find_calls) == 1


def test_none_dangling_bare_oid_skipped_strings_kept(sync):
    db, run = sync
    live = ObjectId()
    db["character"] = _FakeColl([
        {"_id": live, "name": "Live"},
        {"_id": "nameless"},  # row with no name is skipped too
    ])
    content = run({
        "name": "Mira",
        "associations": [
            None,
            _ref("character", ObjectId()),  # dangling
            ObjectId(),                      # bare ObjectId: no collection
            {"_cls": "X", "_ref": None},
            _ref("character", "nameless"),
            "Plain String",
            _ref("character", live),
        ],
    })["content"]
    assert "\nRelated: Plain String, Live\n" in content
    assert "DBRef" not in content and "ObjectId" not in content


def test_only_first_20_associations_resolved(sync):
    db, run = sync
    oids = [ObjectId() for _ in range(25)]
    db["character"] = _FakeColl([{"_id": o, "name": f"n{i}"} for i, o in enumerate(oids)])
    content = run({"name": "Mira", "associations": [_ref("character", o) for o in oids]})["content"]
    related = content.split("\nRelated: ")[1].split("\n")[0]
    assert related.split(", ") == [f"n{i}" for i in range(20)]
    assert db["character"].find_calls[0][0]["_id"]["$in"] == oids[:20]


# ---------------------------------------------------------------------------
# MIN_CONTENT_CHARS gate
# ---------------------------------------------------------------------------


def test_digest_alone_clears_the_gate(sync):
    # Pre-PR the gate only counted name + history + raw associations,
    # so a doc whose substance is all in desc_summary was skipped.
    _, run = sync
    mapping = run({"name": "", "desc_summary": "A long enough summary."})
    assert mapping is not None
    assert mapping["content"].startswith(": A long enough summary.")


def test_resolved_names_count_toward_gate(sync):
    db, run = sync
    oid = ObjectId()
    db["character"] = _FakeColl([{"_id": oid, "name": "Bartholomew"}])
    mapping = run({"name": "M", "associations": [_ref("character", oid)]})
    assert mapping["content"] == "M: \nRelated: Bartholomew\n"


def test_dangling_refs_and_markup_do_not_count(sync):
    # Raw DBRef reprs used to pad the count past the threshold; now a
    # tiny name + dangling refs + tag-only HTML is skipped.
    _, run = sync
    assert run({
        "name": "<i>M</i>",
        "history": "<p></p>" * 10,
        "associations": [_ref("character", ObjectId()) for _ in range(3)],
    }) is None
