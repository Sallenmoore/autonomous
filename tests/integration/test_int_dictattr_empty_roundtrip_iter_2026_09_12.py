"""Live round trip for PR #251 (closes #249) against the Compose Mongo.

save → reload → in-place write on the EMPTY dict → save → reload shows
the value, for both ``DictAttr()`` and ``DictAttr(default=None, null=True)``.
Pre-#249 the empty read handed back a detached plain dict, so the second
``save()`` persisted nothing.
"""

import pytest

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


@pytest.mark.parametrize("field", ["props", "nullable"])
def test_in_place_write_on_empty_dict_persists(field):
    doc = _RoundTripBag(label="x")
    doc.save()

    loaded = _RoundTripBag.get(doc.pk)
    assert getattr(loaded, field) == {}
    getattr(loaded, field)["k"] = "v"
    loaded.save()

    again = _RoundTripBag.get(doc.pk)
    assert getattr(again, field) == {"k": "v"}


def test_reassigning_the_whole_dict_still_works():
    # The consumer-side workaround must keep working.
    doc = _RoundTripBag(label="x")
    doc.save()
    loaded = _RoundTripBag.get(doc.pk)
    loaded.props = {**loaded.props, "k": "v"}
    loaded.save()
    assert _RoundTripBag.get(doc.pk).props == {"k": "v"}
