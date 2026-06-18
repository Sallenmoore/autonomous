"""Pinning tests for ``AutoModel.get`` failure-mode asymmetry (TEST-6 in #141).

Documents the contract in ``automodel.py:268-273``:

- ``DoesNotExist`` → ``None`` (the lookup miss is not exceptional).
- ``ValidationError`` → ``None`` (logged; same "treat as missing" shape).
- ``OperationFailure`` → **re-raised** (infra outage must not silently
  surface as a missing document).
- ``ConnectionFailure`` → **re-raised** (same rationale).

The asymmetry is the whole point and is the only thing standing between a
"consistency cleanup" refactor and silently converting infra failures into
spurious "not found" results. The docstring on ``get`` calls this out
explicitly ("DB outages don't get silently swallowed"); these tests pin it.

Stubbing pattern adapted from ``tests/unit/test_unit_where.py``: the
``Fake`` model class exposes a ``MagicMock`` ``objects`` and binds the real
``AutoModel.get`` classmethod, and the ``_skip_ensure_connected`` autouse
fixture patches ``_ensure_connected`` so no Mongo connection is needed.
"""

from unittest.mock import MagicMock, patch

import bson
import pytest
from pymongo.errors import ConnectionFailure, OperationFailure


@pytest.fixture
def model_class():
    """An AutoModel stand-in with a stubbed ``objects`` and the real ``get``."""
    from autonomous.db.errors import ValidationError as MEValidationError
    from autonomous.model import automodel as am

    class _FakeDoesNotExist(Exception):
        pass

    class Fake:
        objects = MagicMock()
        DoesNotExist = _FakeDoesNotExist
        __name__ = "Fake"

    # Bind the real classmethod so we exercise actual ``get`` behavior.
    Fake.get = classmethod(am.AutoModel.get.__func__)
    Fake._mongo_validation_error = MEValidationError
    return Fake


@pytest.fixture(autouse=True)
def _skip_ensure_connected():
    from autonomous.model import automodel as am

    with patch.object(am, "_ensure_connected"):
        yield


class TestAutoModelGetSwallows:
    """``DoesNotExist`` and ``ValidationError`` resolve to ``None``."""

    def test_doesnotexist_returns_none(self, model_class):
        model_class.objects.get.side_effect = model_class.DoesNotExist

        result = model_class.get(bson.ObjectId())

        assert result is None

    def test_validation_error_returns_none(self, model_class):
        # ValidationError uses the same translation as DoesNotExist:
        # treat as "no valid match" rather than re-raising.
        model_class.objects.get.side_effect = model_class._mongo_validation_error(
            "bad shape"
        )

        result = model_class.get(bson.ObjectId())

        assert result is None

    def test_invalid_pk_string_returns_none_without_query(self, model_class):
        # The pk-coercion branch at automodel.py:254-258 returns None
        # before ``objects.get`` is reached.
        result = model_class.get("not-a-valid-objectid")

        assert result is None
        model_class.objects.get.assert_not_called()


class TestAutoModelGetReraises:
    """Infra outages re-raise — they must NOT be silently masked."""

    def test_operation_failure_reraises(self, model_class):
        model_class.objects.get.side_effect = OperationFailure("cmd failed")

        with pytest.raises(OperationFailure):
            model_class.get(bson.ObjectId())

    def test_connection_failure_reraises(self, model_class):
        model_class.objects.get.side_effect = ConnectionFailure("server gone")

        with pytest.raises(ConnectionFailure):
            model_class.get(bson.ObjectId())


class TestAutoModelGetHappyPath:
    """Happy path returns the matched document."""

    def test_returns_objects_get_result(self, model_class):
        sentinel = object()
        model_class.objects.get.return_value = sentinel

        result = model_class.get(bson.ObjectId())

        assert result is sentinel
