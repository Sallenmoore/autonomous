"""Independent coverage for PR #253 (closes #250): ``auto_pre_init`` no
longer refetches documents built FROM the store.

Written from the PR diff alone (two-perspective rule).

Pinned:

- the vendored ``pre_init`` payload carries ``created`` (True on user
  construction, False on ``_from_son``);
- ``Model._from_son(son)`` never touches the collection;
- ``Model(pk=x)`` still calls ``find_one`` exactly once and caller kwargs
  still win;
- ``Model.from_json(blob)`` still side-loads (blob wins, store fills the
  gaps, one query), yields ``_created is False``, tolerates a stale key on
  a ``strict=False`` model, and its side-load opt-in does not leak past
  the call;
- the hook called directly WITHOUT ``created`` still hydrates, and with
  ``created=False`` does nothing;
- a plain vendored ``Document`` / ``EmbeddedDocument`` constructs with
  ``autonomous.model.automodel`` imported, and the pre/post-save signals
  fire for it without raising (the sender-unfiltered receivers used to
  raise ``AttributeError``);
- ``auto_load_on_init = False`` still opts out entirely.

The live N-docs-zero-refetch measurement lives in
``tests/integration/test_int_pre_init_no_refetch_iter_2026_09_12.py``.
"""

from unittest.mock import MagicMock, patch

import bson
import pytest

from autonomous.db import Document, EmbeddedDocument, StringField, signals
from autonomous.model.autoattr import StringAttr
from autonomous.model.automodel import AutoModel

_OID = bson.ObjectId("507f1f77bcf86cd799439011")


class _Thing(AutoModel):
    name = StringAttr(default="")
    note = StringAttr(default="")


@pytest.fixture
def collection():
    """Stand-in for ``_Thing._get_collection()``; records ``find_one``."""
    coll = MagicMock()
    coll.find_one.return_value = {
        "_id": _OID,
        "_cls": "_Thing",
        "name": "from-db",
        "note": "gap",
    }
    with patch.object(_Thing, "_get_collection", return_value=coll):
        yield coll


class TestPreInitPayloadCarriesCreated:
    @pytest.fixture
    def seen(self):
        seen = []

        def receiver(_sender, **kwargs):
            seen.append(kwargs.get("created", "ABSENT"))

        signals.pre_init.connect(receiver, sender=_Thing)
        try:
            yield seen
        finally:
            signals.pre_init.disconnect(receiver, sender=_Thing)

    def test_user_construction_sends_created_true(self, seen):
        _Thing(name="x")
        assert seen == [True]

    def test_from_son_sends_created_false(self, seen):
        _Thing._from_son({"_id": _OID, "name": "x"})
        assert seen == [False]


class TestConstructionPaths:
    def test_from_son_never_touches_the_collection(self, collection):
        doc = _Thing._from_son({"_id": _OID, "name": "stored"})
        assert doc.name == "stored"
        assert doc._created is False
        collection.find_one.assert_not_called()

    def test_pk_construction_still_hydrates_with_exactly_one_find_one(self, collection):
        doc = _Thing(pk=_OID)
        collection.find_one.assert_called_once_with({"_id": _OID})
        assert doc.name == "from-db"
        assert doc.note == "gap"

    def test_caller_kwargs_still_win_over_the_store(self, collection):
        doc = _Thing(pk=_OID, name="explicit")
        assert collection.find_one.call_count == 1
        assert doc.name == "explicit"
        assert doc.note == "gap"

    def test_from_json_still_side_loads_blob_wins_store_fills_gaps(self, collection):
        # Forward-looking: also holds on the pre-#250 base, where EVERY
        # construction side-loaded. It pins the from_json exception the
        # PR carved out so the skip never widens to cover it.
        doc = _Thing.from_json(bson.json_util.dumps({"_id": _OID, "name": "blob"}))
        assert collection.find_one.call_count == 1
        assert doc.name == "blob"
        assert doc.note == "gap"
        assert doc._created is False

    def test_from_json_tolerates_a_stale_key_on_strict_false_models(self, collection):
        # Constructing with created=True would switch on BaseDocument's
        # undefined-field check; a session blob carrying a field that was
        # since removed from the model then raised FieldDoesNotExist on
        # every current_user() call.
        assert _Thing._meta.get("strict") is False
        doc = _Thing.from_json(
            bson.json_util.dumps({"_id": _OID, "name": "blob", "stale": 1})
        )
        assert collection.find_one.call_count == 1
        assert doc.name == "blob"
        assert doc.note == "gap"
        assert doc._created is False

    def test_from_json_side_load_opt_in_does_not_leak_past_the_call(self, collection):
        _Thing.from_json(bson.json_util.dumps({"_id": _OID, "name": "blob"}))
        _Thing._from_son({"_id": _OID, "name": "stored"})
        assert collection.find_one.call_count == 1

    @pytest.mark.usefixtures("collection")
    def test_from_json_created_kwarg_is_honoured(self):
        doc = _Thing.from_json(
            bson.json_util.dumps({"_id": _OID, "name": "blob"}), created=True
        )
        assert doc._created is True

    def test_opt_out_still_skips_the_fetch(self):
        class _Quiet(AutoModel):
            auto_load_on_init = False
            name = StringAttr(default="")

        with patch.object(_Quiet, "_get_collection") as get_collection:
            doc = _Quiet(pk=_OID)
        get_collection.assert_not_called()
        assert doc.pk == _OID


class TestHookCalledDirectly:
    @staticmethod
    def _sender():
        sender = MagicMock()
        sender._get_collection.return_value.find_one.return_value = {
            "_id": _OID,
            "name": "from-db",
        }
        return sender

    def test_without_created_still_hydrates(self):
        sender = self._sender()
        values = {"pk": str(_OID)}
        AutoModel.auto_pre_init(sender, document=None, values=values)
        assert values["name"] == "from-db"

    def test_created_true_hydrates(self):
        sender = self._sender()
        values = {"pk": str(_OID)}
        AutoModel.auto_pre_init(sender, document=None, values=values, created=True)
        assert values["name"] == "from-db"

    def test_created_false_does_nothing(self):
        sender = self._sender()
        values = {"pk": str(_OID)}
        AutoModel.auto_pre_init(sender, document=None, values=values, created=False)
        sender._get_collection.assert_not_called()
        assert values == {"pk": str(_OID)}

    def test_subclass_override_with_kwargs_receives_created(self):
        class _Sub:
            seen = {}

            @classmethod
            def auto_pre_init(cls, _sender, _document, **kwargs):
                cls.seen.update(kwargs)

        AutoModel._auto_pre_init(_Sub, document=None, values={}, created=False)
        assert _Sub.seen["created"] is False


class TestSenderUnfilteredReceiversAreGuarded:
    def test_plain_embedded_document_constructs(self):
        class _Emb(EmbeddedDocument):
            name = StringField()

        assert _Emb(name="x").name == "x"

    def test_plain_document_constructs(self):
        class _Plain(Document):
            name = StringField()

        assert _Plain(name="y").name == "y"

    def test_plain_document_save_signals_do_not_raise(self):
        # save() fires pre_save / post_save through the same unfiltered
        # receivers; send them directly so no connection is needed.
        class _PlainSaved(Document):
            name = StringField()

        doc = _PlainSaved(name="y")
        signals.pre_save.send(_PlainSaved, document=doc)
        signals.post_save.send(_PlainSaved, document=doc, created=True)

    def test_delegators_tolerate_a_sender_without_hooks(self):
        class _NoHooks:
            pass

        AutoModel._auto_pre_init(_NoHooks, document=None, values={}, created=True)
        AutoModel._auto_post_init(_NoHooks, document=None)
