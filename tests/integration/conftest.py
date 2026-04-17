"""Shared conftest for integration tests.

Marks every test in this directory with ``@pytest.mark.integration`` so
the default ``pytest`` run (scoped to ``tests/unit`` via pyproject) won't
discover them. Run integration tests explicitly:

    pytest tests/integration
    pytest -m integration

The Makefile wires ``make test-int`` to the latter.
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Attach the ``integration`` marker to every item collected here."""
    integration_mark = pytest.mark.integration
    for item in items:
        item.add_marker(integration_mark)
