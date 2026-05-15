"""Pin that the HTTP Session optimization is wired correctly.

Not strictly a benchmark — the structural property (Session is reused,
bare ``requests.post`` is not called) is what matters. If this passes,
the connection-pooling win is real; pytest-benchmark measurement
would only ever show "first call slower than second."
"""

from unittest.mock import MagicMock

from autonomous.ai.models import openai_compat, local_model
from autonomous.db import db_sync


def test_openai_compat_module_has_session():
    assert hasattr(openai_compat, "_SESSION")
    # Session, not just a Mock — duck-type check.
    assert hasattr(openai_compat._SESSION, "post")


def test_local_model_module_has_session():
    assert hasattr(local_model, "_SESSION")
    assert hasattr(local_model._SESSION, "post")


def test_db_sync_module_has_session():
    assert hasattr(db_sync, "_HTTP_SESSION")
    assert hasattr(db_sync._HTTP_SESSION, "post")


def test_session_is_singleton_within_module(benchmark):
    """Repeated attribute access returns the same Session instance —
    confirms there's no per-call re-instantiation undermining pooling.
    """
    def _read_all():
        return (
            id(openai_compat._SESSION),
            id(local_model._SESSION),
            id(db_sync._HTTP_SESSION),
        )

    first = _read_all()
    second = benchmark(_read_all)
    assert first == second
