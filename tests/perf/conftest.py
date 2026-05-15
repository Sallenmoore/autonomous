"""Conftest for the opt-in perf benchmark suite.

Marks every test in this directory with @pytest.mark.perf so they
don't accidentally run as part of the default `pytest tests/unit/`
gate. Invoke explicitly:

    pytest tests/perf --benchmark-only
    make test-perf
"""

import pytest

pytestmark = pytest.mark.perf
