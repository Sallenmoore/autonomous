"""Conftest for the opt-in perf benchmark suite.

Applies ``@pytest.mark.perf`` to every test collected from this
directory via ``pytest_collection_modifyitems``. Invoke explicitly:

    pytest tests/perf --benchmark-only
    pytest -m perf
    make test-perf

Why the collection hook and not a module-level ``pytestmark``:
``pytestmark`` only applies to tests collected *from the module
declaring it*. A conftest.py contains no collected tests of its own,
so a ``pytestmark = pytest.mark.perf`` declaration there is a no-op
(it does NOT propagate to sibling test files — well-known pytest
gotcha, see issue #80). The collection hook is the documented
correct mechanism for marker propagation across a directory.

Default ``pytest`` invocation still excludes this directory via the
``testpaths = ["tests/unit"]`` setting in ``pyproject.toml`` — that
remains the load-bearing exclusion. The marker exists so the explicit
``-m perf`` filter works (and so ``-m 'not perf'`` cleanly excludes
benchmarks from a wider sweep).
"""


def pytest_collection_modifyitems(config, items):
    """Tag every test under tests/perf/ with the ``perf`` marker.

    Iterates over the collected ``items`` and applies the marker to
    anything whose path is under this conftest's directory. The
    ``config`` param is part of the hook signature (unused here).
    """
    import pathlib

    import pytest

    perf_dir = pathlib.Path(__file__).parent.resolve()
    for item in items:
        # item.path is a py.path.local or pathlib.Path depending on
        # pytest version; resolve both to a string for the prefix
        # check.
        item_path = pathlib.Path(str(item.path)).resolve()
        try:
            item_path.relative_to(perf_dir)
        except ValueError:
            continue
        item.add_marker(pytest.mark.perf)
