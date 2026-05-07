"""Unit-test conftest: skip pydub-dependent suites on Python 3.13+.

pydub <0.26 imports the stdlib ``audioop`` module at load, which was
removed in Python 3.13. The ``pyaudioop`` backport pydub falls back to
also doesn't support 3.13 yet. Until pydub ships a 3.13-compatible
release, any test that transitively imports it (audioagent, gemini,
temperature_override) errors at collection on the 3.13 matrix entry.

Suppressing collection here keeps CI green on 3.13 for the rest of the
suite. 3.11 / 3.12 still exercise the affected tests fully. Remove this
block once pydub is updated.
"""

import sys

if sys.version_info >= (3, 13):
    collect_ignore_glob = [
        "test_unit_audioagent.py",
        "test_unit_gemini_env_models.py",
        "test_unit_mutable_defaults.py",
        "test_unit_temperature_override.py",
    ]
