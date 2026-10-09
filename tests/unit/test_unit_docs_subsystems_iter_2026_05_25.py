"""Independent coverage for PR #123 (docs: mention cli.py and utils in
CLAUDE.md "Other subsystems").

PR #123 adds two bullets to CLAUDE.md naming ``src/autonomous/cli.py``
and ``src/autonomous/utils/`` so future readers don't think those
files are vestigial. The dev-side ephemeral test (gitignored) almost
certainly just greps the file for the two strings.

This file pins a stronger invariant: the **referenced things actually
exist** at the paths CLAUDE.md cites. A future "clean up vestigial
modules" PR that removes ``cli.py`` or ``utils/markdown.py`` should
fail here too — not just produce a CLAUDE.md that points at nothing.

Hermetic: pure filesystem reads, no imports beyond stdlib.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
SRC = REPO / "src" / "autonomous"


# ---------------------------------------------------------------------------
# The doc reference holds
# ---------------------------------------------------------------------------


class TestClaudeMdMentions:
    def test_utils_mention_present(self):
        text = CLAUDE_MD.read_text(encoding="utf-8")
        assert "src/autonomous/utils/" in text, (
            "CLAUDE.md no longer mentions src/autonomous/utils/ — same "
            "concern as the cli.py mention; it's the shared-helpers home."
        )

    def test_mentions_live_in_other_subsystems_section(self):
        """Pin the structural placement: both bullets should live under
        the "Other subsystems" heading, not scattered elsewhere.
        Otherwise future doc reshuffles could split them and the
        "small utility modules" framing is lost.
        """
        text = CLAUDE_MD.read_text(encoding="utf-8")
        # Locate the "Other subsystems" heading and the next ## heading
        # after it; the cli + utils bullets must live in that window.
        match = re.search(
            r"### Other subsystems\n(.*?)(?=\n## |\n### )",
            text,
            re.DOTALL,
        )
        assert match, "CLAUDE.md no longer has an '### Other subsystems' section"
        section = match.group(1)
        assert "utils" in section, "utils/ mention drifted out of 'Other subsystems'"


# ---------------------------------------------------------------------------
# The referenced things actually exist
# ---------------------------------------------------------------------------


class TestReferencedFilesExist:
    """If CLAUDE.md cites a path, that path should resolve. Otherwise
    PR #123's bullets become "documentation rot" — they point at modules
    that were deleted later, misleading future readers more than the
    pre-PR omission would have."""

    def test_utils_package_exists(self):
        utils = SRC / "utils"
        assert utils.is_dir(), "src/autonomous/utils/ no longer exists"

    def test_utils_markdown_module_exists(self):
        """CLAUDE.md says utils currently has "just ``markdown.py``".
        If markdown.py is gone AND nothing replaces it, the bullet is
        inaccurate; if other modules were added that's fine (the
        bullet says "currently just"), but markdown.py going missing
        is a regression."""
        md = SRC / "utils" / "markdown.py"
        assert md.exists(), (
            "src/autonomous/utils/markdown.py is gone — CLAUDE.md "
            "references it as the sole utility today; either move it "
            "or update the bullet to point at the replacement."
        )
