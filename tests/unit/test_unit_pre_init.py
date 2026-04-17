"""Item 13: hardening for AutoModel.auto_pre_init.

The hook side-loads stored fields when a caller does ``Model(pk=...)``
without other kwargs. Three real bugs in the original:

1. ``not values.get(k)`` clobbered legitimate falsy values (0, False,
   "", []) by replacing them with the DB value.
2. No defense against ``values=None`` -> AttributeError on ``.get``.
3. Bad ``pk`` (not a valid ObjectId) raised ``InvalidId`` from inside
   ``__init__`` — confusing.

Plus: no opt-out. Apps that don't want a Mongo round trip per construct
had no way to skip the hook.

These tests pin the new contract.
"""

from unittest.mock import MagicMock, patch

import bson
import pytest


@pytest.fixture
def autoauth_module():
    from autonomous.model import automodel

    return automodel


def test_returns_when_values_missing(autoauth_module):
    """If kwargs has no ``values`` key, do nothing and don't crash."""
    sender = MagicMock()
    autoauth_module.AutoModel.auto_pre_init(sender, document=None)
    sender._get_collection.assert_not_called()


def test_returns_when_values_empty(autoauth_module):
    sender = MagicMock()
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values={})
    sender._get_collection.assert_not_called()


def test_returns_when_no_pk_in_values(autoauth_module):
    sender = MagicMock()
    values = {"name": "x"}
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
    sender._get_collection.assert_not_called()
    assert values == {"name": "x"}


def test_returns_when_pk_is_not_a_valid_objectid(autoauth_module):
    sender = MagicMock()
    values = {"pk": "definitely-not-an-oid"}
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
    sender._get_collection.assert_not_called()
    # Caller's kwargs are untouched — no garbage merged in.
    assert values == {"pk": "definitely-not-an-oid"}


def test_returns_when_doc_not_found(autoauth_module):
    sender = MagicMock()
    sender._get_collection.return_value.find_one.return_value = None
    values = {"pk": "507f1f77bcf86cd799439011"}
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
    assert values == {"pk": "507f1f77bcf86cd799439011"}


def test_merges_missing_fields_from_db(autoauth_module):
    sender = MagicMock()
    sender._get_collection.return_value.find_one.return_value = {
        "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
        "_cls": "SomeModel",
        "name": "from-db",
        "count": 7,
    }
    values = {"pk": "507f1f77bcf86cd799439011"}
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
    assert values["name"] == "from-db"
    assert values["count"] == 7
    # Mongoengine internals stripped.
    assert "_id" not in values
    assert "_cls" not in values


def test_caller_kwargs_win(autoauth_module):
    sender = MagicMock()
    sender._get_collection.return_value.find_one.return_value = {
        "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
        "name": "from-db",
    }
    values = {"pk": "507f1f77bcf86cd799439011", "name": "explicit"}
    autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
    assert values["name"] == "explicit"


class TestPreservesFalsyCallerValues:
    """The fix for the ``not values.get(k)`` bug."""

    def test_zero_is_preserved(self, autoauth_module):
        sender = MagicMock()
        sender._get_collection.return_value.find_one.return_value = {
            "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
            "count": 99,
        }
        values = {"pk": "507f1f77bcf86cd799439011", "count": 0}
        autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
        assert values["count"] == 0

    def test_false_is_preserved(self, autoauth_module):
        sender = MagicMock()
        sender._get_collection.return_value.find_one.return_value = {
            "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
            "active": True,
        }
        values = {"pk": "507f1f77bcf86cd799439011", "active": False}
        autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
        assert values["active"] is False

    def test_empty_string_is_preserved(self, autoauth_module):
        sender = MagicMock()
        sender._get_collection.return_value.find_one.return_value = {
            "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
            "note": "from-db",
        }
        values = {"pk": "507f1f77bcf86cd799439011", "note": ""}
        autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
        assert values["note"] == ""

    def test_empty_list_is_preserved(self, autoauth_module):
        sender = MagicMock()
        sender._get_collection.return_value.find_one.return_value = {
            "_id": bson.ObjectId("507f1f77bcf86cd799439011"),
            "tags": ["a", "b"],
        }
        values = {"pk": "507f1f77bcf86cd799439011", "tags": []}
        autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
        assert values["tags"] == []


class TestOptOut:
    def test_auto_load_on_init_false_skips_db(self, autoauth_module):
        # Mock a sender that has the opt-out attribute. We don't define a
        # real subclass because mongoengine's metaclass would require a
        # live connection for class registration.
        sender = MagicMock()
        sender.auto_load_on_init = False
        values = {"pk": "507f1f77bcf86cd799439011"}
        autoauth_module.AutoModel.auto_pre_init(sender, document=None, values=values)
        sender._get_collection.assert_not_called()


class TestDbErrorIsSwallowed:
    def test_operation_failure_does_not_propagate(self, autoauth_module):
        from pymongo.errors import OperationFailure

        sender = MagicMock()
        sender.__name__ = "SomeModel"
        sender._get_collection.return_value.find_one.side_effect = OperationFailure(
            "db down"
        )
        values = {"pk": "507f1f77bcf86cd799439011"}
        # Must not raise — instantiation continues even if DB hiccups.
        autoauth_module.AutoModel.auto_pre_init(
            sender, document=None, values=values
        )
        assert "name" not in values  # nothing was merged
