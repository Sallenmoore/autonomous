"""Tests for the audioop-lts pin (issue #24, PR #37).

Python 3.13 removed ``audioop`` from the stdlib (PEP 594). ``pydub`` —
pulled by ``autonomous.ai.models.gemini`` for audio post-processing —
imports ``audioop`` at module load, so on 3.13+ any code that touched
``autonomous.ai.*`` exploded with ``ModuleNotFoundError: No module named
'audioop'``.

Fix: ``requirements-ai.txt`` now pins ``audioop-lts; python_version >=
"3.13"``. ``audioop-lts`` is the actively-maintained drop-in that
provides the ``audioop`` module name, so the legacy import keeps
working without library changes elsewhere.

These tests pin the contract so a future cleanup that drops the marker
(e.g., a dep refresh that doesn't preserve env markers) will fail unit
tests before it ships.
"""

import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
REQ_AI = REPO_ROOT / "requirements-ai.txt"


class TestRequirementsPin:
    """Pin the requirements-ai.txt entry that fixes issue #24."""

    def test_audioop_lts_listed(self):
        text = REQ_AI.read_text()
        assert re.search(
            r"^\s*audioop-lts\b", text, re.M
        ), (
            "requirements-ai.txt must list 'audioop-lts' — pydub imports "
            "fail on Python 3.13+ without it (issue #24)."
        )

    def test_marker_scopes_to_python_3_13_or_later(self):
        # The marker keeps 3.11/3.12 environments from picking up the
        # backport unnecessarily. If a future edit drops the marker,
        # 3.11/3.12 install would still work (audioop-lts is harmless on
        # them) but the install footprint grows. Pin the contract.
        text = REQ_AI.read_text()
        match = re.search(
            r"^\s*audioop-lts\s*;\s*python_version\s*>=\s*[\"']3\.13[\"']",
            text,
            re.M,
        )
        assert match, (
            "audioop-lts entry must carry the marker "
            '`python_version >= "3.13"` so 3.11/3.12 environments '
            "skip the install. Found:\n"
            + "\n".join(
                line for line in text.splitlines() if "audioop" in line
            )
        )


class TestAudioopShimAvailable:
    """Behavioral: on the affected Python versions the shim must work."""

    @pytest.mark.skipif(
        sys.version_info < (3, 13),
        reason="audioop is in stdlib on 3.11/3.12; nothing to test",
    )
    def test_audioop_importable_on_py313_plus(self):
        # If the requirements-ai.txt pin is correct AND CI installed it,
        # `import audioop` resolves to audioop-lts. If the pin is wrong
        # or skipped, this raises ModuleNotFoundError — the same failure
        # shape as issue #24.
        import audioop  # noqa: F401  (import-only — presence is the test)

    @pytest.mark.skipif(
        sys.version_info < (3, 13),
        reason="pydub-via-audioop only breaks on 3.13+",
    )
    def test_pydub_importable_on_py313_plus(self):
        # End-to-end repro of issue #24: importing pydub triggered
        # `import audioop` deep in pydub.utils, which crashed on 3.13.
        # With audioop-lts installed, this succeeds.
        from pydub import AudioSegment  # noqa: F401

    @pytest.mark.skipif(
        sys.version_info < (3, 13),
        reason="autonomous.ai.* import chain only breaks on 3.13+ via pydub",
    )
    def test_autonomous_ai_baseagent_importable(self):
        # The original symptom path from the issue body:
        #   autonomous.ai.baseagent → autonomous.ai.models.gemini → pydub → audioop
        # Importing the top of the chain is the lowest-cost regression check.
        import autonomous.ai.baseagent  # noqa: F401
