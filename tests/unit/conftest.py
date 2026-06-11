"""Unit-test conftest.

Historical note: this file used to skip the pydub-dependent suites on
Python 3.13+ because pydub's `import audioop` exploded on 3.13 (PEP 594
removed audioop from stdlib). PR #37 / issue #24 fixed that at the dep
layer by pinning `audioop-lts` in requirements-ai.txt, so the skip
block is no longer needed — the affected tests now run cleanly on
every leg of the matrix.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_unsupported_strict_mode_cache():
    """Snapshot + restore ``openai_compat._UNSUPPORTED_STRICT_MODE`` around
    every unit test (issue #105).

    ``_UNSUPPORTED_STRICT_MODE`` is a process-global ``set`` memoizing the
    ``(model, endpoint)`` pairs that probed as strict-mode-unsupported, so
    the adapter doesn't re-probe them every call. Multiple unit test files
    mutate it (``.add`` / ``.discard`` / ``.clear``) without restoring
    state at teardown — known sites include
    ``test_unit_openai_compat_structured_outputs.py``,
    ``test_unit_json_schema_structured_outputs_iter_2026-06-03.py``,
    ``test_unit_openai_compat_malformed_iter_2026-06-11.py``,
    ``test_unit_gemini_image_size_strict_dialect_iter_2026-06-04.py``,
    and the ``TestStrictModeCacheIsolation`` pair in
    ``test_unit_httpclient_ai_error_handling_followups_iter_2026-06-11e.py``
    that self-validates this fixture. In pytest's collection order a leaked cache entry
    would make a later test silently SKIP the strict probe it meant to
    exercise — order-dependent flakiness that surfaces the moment a new
    openai_compat test lands. PR #95/#99 acknowledged the fragility but
    left the fix to the test agent's exclusive surface (a conftest
    ``autouse`` fixture).

    Snapshot-and-restore (rather than ``clear``) so the fixture is
    symmetric for tests that ADD entries (cleared on restore) and tests
    that REMOVE/clear entries (re-added on restore). The import is lazy so
    a unit test that never touches the adapter still pays only the (cached)
    import + a tiny ``set`` copy. Scoped to ``tests/unit/`` because every
    known consumer is a unit test; widen to ``tests/conftest.py`` only if
    an integration test starts mutating the cache.
    """
    from autonomous.ai.models import openai_compat

    cache = openai_compat._UNSUPPORTED_STRICT_MODE
    snapshot = set(cache)
    try:
        yield
    finally:
        cache.clear()
        cache.update(snapshot)
