"""Item 20: chainable query API for AutoModel.

``AutoModel.where(**kwargs)`` returns the underlying mongoengine
QuerySet so consumers can chain ``.order_by() / .limit() / .skip() /
.first() / .count()`` without re-materializing. ``.search()`` stays as
it was (returns a list) for backward compatibility.

These tests don't require MongoDB. The ORM's objects manager is
stubbed; assertions are on the kwargs forwarded and whether the
returned object is the stubbed queryset (i.e. chaining survived).
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def model_class():
    """Return an AutoModel stand-in whose `objects` is a callable mock."""
    from autonomous.model import automodel as am

    class Fake:
        objects = MagicMock()

    # Bind AutoModel.where as a classmethod on Fake so Fake.where(...)
    # exercises the real implementation against our stubbed `objects`.
    Fake.where = classmethod(am.AutoModel.where.__func__)
    return Fake


@pytest.fixture(autouse=True)
def _skip_ensure_connected():
    from autonomous.model import automodel as am

    with patch.object(am, "_ensure_connected"):
        yield


class TestWhereReturnsQuerySet:
    def test_where_returns_whatever_objects_returns(self, model_class):
        model_class.objects.return_value = "the-queryset"
        result = model_class.where(name="alice")
        assert result == "the-queryset"

    def test_string_values_become_icontains(self, model_class):
        model_class.where(name="alice", email="@example.com")
        kwargs = model_class.objects.call_args.kwargs
        assert kwargs == {
            "name__icontains": "alice",
            "email__icontains": "@example.com",
        }

    def test_non_string_values_pass_through(self, model_class):
        model_class.where(views=42, published=True)
        kwargs = model_class.objects.call_args.kwargs
        assert kwargs == {"views": 42, "published": True}

    def test_explicit_operator_is_preserved(self, model_class):
        # A key containing `__` means the caller already picked a mongo
        # operator — don't re-wrap it as icontains.
        model_class.where(views__gt=1000, title__regex="^intro")
        kwargs = model_class.objects.call_args.kwargs
        assert kwargs == {"views__gt": 1000, "title__regex": "^intro"}

    def test_mix_of_string_and_operator(self, model_class):
        model_class.where(name="alice", views__gt=0)
        kwargs = model_class.objects.call_args.kwargs
        assert kwargs == {"name__icontains": "alice", "views__gt": 0}


class TestWhereEnablesChaining:
    def test_order_by_then_limit(self, model_class):
        queryset = MagicMock(name="QuerySet")
        model_class.objects.return_value = queryset

        result = model_class.where(name="alice").order_by("-created").limit(5)

        queryset.order_by.assert_called_once_with("-created")
        queryset.order_by.return_value.limit.assert_called_once_with(5)
        assert result is queryset.order_by.return_value.limit.return_value

    def test_first_returns_first_result(self, model_class):
        queryset = MagicMock(name="QuerySet")
        queryset.first.return_value = "alice-instance"
        model_class.objects.return_value = queryset

        result = model_class.where(name="alice").first()
        assert result == "alice-instance"

    def test_count_on_where(self, model_class):
        queryset = MagicMock(name="QuerySet")
        queryset.count.return_value = 3
        model_class.objects.return_value = queryset

        assert model_class.where(published=True).count() == 3
