"""Live round trip for PR #251 (closes #249) against the Compose Mongo.

save → reload → in-place write on the EMPTY dict → save → reload shows
the value. Pre-#249 the empty read handed back a detached plain dict, so
the second ``save()`` persisted nothing.

For ``DictAttr(default=None, null=True)``: constructing a document reads
the field through the descriptor, so the ORM itself stores ``{}`` — a
stored ``null`` only arises from an explicit ``doc.field = None`` or an
external writer, which is what ``_null_out`` simulates. That read heals
to a bound ``{}`` WITHOUT marking the field, so an unrelated save leaves
the null in place; an in-place write on it emits ``$set foo.k``, which
Mongo rejects on a null parent — loud, where the old code dropped the
write silently — and whole-dict reassignment is the way through.
"""

import pytest

from autonomous.db import OperationError
from autonomous.model import automodel
from autonomous.model.autoattr import DictAttr, StringAttr
from autonomous.model.automodel import AutoModel


class _RoundTripBag(AutoModel):
    label = StringAttr(default="")
    props = DictAttr()
    nullable = DictAttr(default=None, null=True)


@pytest.fixture(autouse=True)
def _clean_collection():
    automodel._ensure_connected()
    _RoundTripBag.drop_collection()
    yield
    _RoundTripBag.drop_collection()


def _saved():
    doc = _RoundTripBag(label="x")
    doc.save()
    return doc.pk


def _stored(pk):
    return _RoundTripBag._get_collection().find_one({"_id": pk})


def _null_out(pk, field):
    """An external writer (or ``doc.field = None; doc.save()``) leaving a
    real ``null`` in the row — the ORM's own construction path never does."""
    _RoundTripBag._get_collection().update_one({"_id": pk}, {"$set": {field: None}})
    assert _stored(pk)[field] is None


def test_in_place_write_on_empty_dict_persists():
    pk = _saved()
    loaded = _RoundTripBag.get(pk)
    assert loaded.props == {}
    loaded.props["k"] = "v"
    loaded.save()
    assert _RoundTripBag.get(pk).props == {"k": "v"}


def test_reassigning_the_whole_dict_still_works():
    # The consumer-side workaround must keep working.
    pk = _saved()
    loaded = _RoundTripBag.get(pk)
    loaded.props = {**loaded.props, "k": "v"}
    loaded.save()
    assert _RoundTripBag.get(pk).props == {"k": "v"}


def test_fresh_document_stores_an_empty_dict_not_null():
    # Construction reads the field through the descriptor, so even the
    # nullable shape lands as {} — unchanged from before #249.
    pk = _saved()
    assert _stored(pk)["nullable"] == {}
    assert _stored(pk)["props"] == {}


def test_nullable_read_is_side_effect_free():
    pk = _saved()
    _null_out(pk, "nullable")
    loaded = _RoundTripBag.get(pk)
    assert loaded.nullable == {}
    loaded.label = "y"
    loaded.save()
    # The bare read must not have queued {} over the stored null.
    assert _stored(pk)["nullable"] is None


def test_nullable_in_place_write_on_a_stored_null_fails_loudly():
    pk = _saved()
    _null_out(pk, "nullable")
    loaded = _RoundTripBag.get(pk)
    loaded.nullable["k"] = "v"
    with pytest.raises(OperationError):
        loaded.save()
    assert _stored(pk)["nullable"] is None


def test_nullable_whole_dict_reassignment_persists():
    pk = _saved()
    _null_out(pk, "nullable")
    loaded = _RoundTripBag.get(pk)
    loaded.nullable = {**loaded.nullable, "k": "v"}
    loaded.save()
    assert _RoundTripBag.get(pk).nullable == {"k": "v"}
