"""Independent coverage for PR #119 (gitignore runtime artifacts).

PR #119 added three patterns to ``.gitignore`` so that runtime memory
artifacts produced by the agent toolchain stop showing up as untracked
noise in every ``git status`` and don't accidentally land in commits:

- ``agentdb.rvf``       — AgentDB store
- ``agentdb.rvf.lock``  — AgentDB lock file
- ``graphify-out/``     — /graphify skill output directory

A pure text-presence test would be easy to satisfy with a misplaced
entry (e.g. inside a quoted comment block, or under a negation).
Instead we shell out to ``git check-ignore`` so the assertion measures
what git would actually do — that's the property we care about.

Skipped (not failed) if the test isn't running inside a git work tree
or git is unavailable; that's the only case where check-ignore can't
answer the question."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]


def _git_available() -> bool:
    return shutil.which("git") is not None and (REPO / ".git").exists()


pytestmark = pytest.mark.skipif(
    not _git_available(),
    reason="git not available or not a git work tree",
)


def _ignored(path: str) -> bool:
    """Return True if git would ignore ``path`` (relative to REPO).

    ``git check-ignore`` exits 0 when the path IS ignored, 1 when it
    isn't, and 128 on error. Any other exit code propagates as a test
    error so we don't silently treat infra problems as "not ignored"."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    pytest.fail(
        f"git check-ignore failed for {path!r} with exit {result.returncode}"
    )
    return False  # unreachable; satisfies type checkers


@pytest.mark.parametrize(
    "path",
    [
        "agentdb.rvf",
        "agentdb.rvf.lock",
        # A file inside the directory — gitignore patterns like
        # ``graphify-out/`` only match the dir itself, so check a
        # representative child to confirm the trailing slash didn't
        # accidentally drop.
        "graphify-out/index.html",
    ],
)
def test_runtime_artifact_is_ignored(path):
    assert _ignored(path), (
        f"{path!r} is not ignored — PR #119's gitignore entry didn't take effect "
        "(check pattern formatting, trailing newline, or negation)."
    )


def test_gitignore_entries_have_explanatory_comments():
    """The PR description argues these are runtime artifacts. The
    .gitignore entries should carry a short comment explaining *why*
    — otherwise the next maintainer wondering "what is agentdb.rvf?"
    has to dig through chat history."""
    text = (REPO / ".gitignore").read_text(encoding="utf-8")

    # Find the agentdb.rvf line and confirm a comment precedes it
    # within a few lines (the actual section header).
    lines = text.splitlines()
    idx = next(
        (i for i, line in enumerate(lines) if line.strip() == "agentdb.rvf"),
        None,
    )
    assert idx is not None, "agentdb.rvf line missing from .gitignore"
    # Walk back up to 5 lines looking for a comment.
    preceding = lines[max(0, idx - 5):idx]
    assert any(line.lstrip().startswith("#") for line in preceding), (
        "agentdb.rvf entry has no explanatory comment in the "
        "preceding 5 lines — future maintainers will have to guess."
    )
