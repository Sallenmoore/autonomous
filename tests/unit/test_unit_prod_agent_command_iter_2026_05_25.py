"""Independent coverage for PR #126 (docs: /prod-agent slash command +
finish /opt/data path migration).

PR #126 adds ``.claude/commands/prod-agent.md`` (a new project-local
slash command), updates ``.gitignore`` to whitelist .claude/commands/
and .claude/agents/, and refactors CLAUDE.md's three-agent pipeline
section to point at the slash command rather than carrying the
inline procedure.

The dev/prod-agent perspective on this work is "I changed the docs and
the procedure file." The test agent's independent perspective is
"are the things the docs now reference actually structurally sound,
and does the new slash command survive the same kind of tree-move
incident that lost /test-agent before this PR?"

Hermetic: filesystem reads + a `git check-ignore` subprocess to assert
the gitignore whitelist works in this clone. No GitHub or PyPI calls.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
COMMANDS = REPO / ".claude" / "commands"


# ---------------------------------------------------------------------------
# The /prod-agent slash command file exists with the expected shape
# ---------------------------------------------------------------------------


class TestProdAgentCommandFile:
    def test_command_file_exists(self):
        path = COMMANDS / "prod-agent.md"
        assert path.exists(), (
            ".claude/commands/prod-agent.md is missing — PR #126 promised "
            "to add the /prod-agent slash command. If the file vanished, "
            "the procedure becomes 'whatever Claude remembers today', "
            "which is exactly the failure mode the PR was meant to fix."
        )

    def test_has_yaml_frontmatter_with_description(self):
        """Same shape as /dev-agent and /test-agent — markdown body
        gated by a YAML frontmatter block whose only required field
        is ``description``."""
        text = (COMMANDS / "prod-agent.md").read_text(encoding="utf-8")
        match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        assert match, "prod-agent.md is missing the YAML frontmatter block"
        frontmatter = match.group(1)
        assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE), (
            "prod-agent.md frontmatter has no description: line"
        )

    # NOTE (2026-06-06): prod-agent.md was converted to a *thin
    # dispatcher* (commit c5aef99, mirroring the test-agent.md conversion
    # in f093772). The step-by-step procedure — the "Do NOT loop / no
    # polling" invariant, the auto-release ship-or-skip gate, and the
    # [smoke-fail] issue lifecycle — moved OUT of this file into the
    # shared template at /opt/stacks/agent-runner/templates/prod-agent.md.
    # That template lives in the agent-runner repo, NOT here, and is
    # absent in CI's clean checkout, so this repo can no longer assert the
    # procedure prose. What it CAN pin is that the dispatcher's delegation
    # is intact and the project values it injects are correct — a
    # dispatcher that forgets to reference the template, or hands the
    # wrong deploy/verify values, silently reverts prod to "whatever
    # Claude remembers today", the exact failure mode PR #126 fixed.
    # The procedure-prose invariants are now the agent-runner repo's test
    # surface.

    def test_dispatcher_delegates_to_shared_template(self):
        """A thin dispatcher must name the canonical template and tell the
        agent to read + execute it. Losing this reference is the
        regression class PR #126 guarded against (procedure goes missing)."""
        text = (COMMANDS / "prod-agent.md").read_text(encoding="utf-8")
        assert "templates/prod-agent.md" in text, (
            "/prod-agent dispatcher no longer references the shared "
            "template — the procedure becomes unreachable."
        )
        assert re.search(r"\bRead that file\b", text) and "execute it" in text, (
            "/prod-agent dispatcher no longer instructs the agent to "
            "read + execute the referenced template."
        )

    def test_pypi_release_values_declared(self):
        """The dispatcher hands the shared template the pypi-deploy values
        so the template's §4/§5 run the release+smoke flow (vs a service
        deploy). If DEPLOY_TYPE / DEPLOY_CMD drift, the auto-release gate
        the template enforces gets the wrong deploy command to gate."""
        text = (COMMANDS / "prod-agent.md").read_text(encoding="utf-8")
        assert re.search(r"DEPLOY_TYPE\s*=\s*pypi", text), (
            "/prod-agent dispatcher dropped DEPLOY_TYPE = pypi — the "
            "template would no longer select the release flow."
        )
        assert "scripts/release.sh" in text, (
            "/prod-agent dispatcher no longer declares scripts/release.sh "
            "as the deploy command."
        )

    def test_smoke_verification_value_declared(self):
        """smoke_test.sh produces the SIGNATURE line the template's
        [smoke-fail] issue lifecycle parses. The dispatcher must pass it
        as SMOKE_CMD and select the pypi_probe verify type. (The
        [smoke-fail] lifecycle prose itself now lives in the shared
        template, out of this repo.)"""
        text = (COMMANDS / "prod-agent.md").read_text(encoding="utf-8")
        assert "scripts/smoke_test.sh" in text
        assert re.search(r"VERIFY_TYPE\s*=\s*pypi_probe", text), (
            "/prod-agent dispatcher no longer selects pypi_probe "
            "verification — post-release smoke would not run."
        )


# ---------------------------------------------------------------------------
# .gitignore whitelist actually works
# ---------------------------------------------------------------------------


class TestClaudeCommandsTracked:
    """Repeat of the lesson PR #126 codified: ``.claude/commands/`` and
    ``.claude/agents/`` must be whitelisted, but per-clone state
    (``cache/``, ``scheduled_tasks.lock``, etc.) must stay ignored.
    Verify both halves with ``git check-ignore`` subprocesses so the
    whitelist isn't accidentally too narrow or too wide."""

    def _check_ignore(self, path: str) -> bool:
        """Return True if ``path`` is currently ignored by git."""
        result = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", path],
            check=False,
        )
        # check-ignore -q: exit 0 if ignored, 1 if not ignored
        return result.returncode == 0

    def test_commands_directory_not_ignored(self):
        assert not self._check_ignore(".claude/commands/prod-agent.md"), (
            ".claude/commands/prod-agent.md is ignored by git — the "
            ".gitignore whitelist is too narrow. /prod-agent will be "
            "lost on the next tree move, defeating the entire purpose "
            "of PR #126."
        )

    def test_test_agent_command_not_ignored(self):
        """Sister-command pin — the /test-agent file should be tracked
        too, since we added the whitelist in the manual housekeeping
        commit. If a future .gitignore edit narrows the whitelist to
        only /prod-agent's directory shape, /test-agent goes missing."""
        assert not self._check_ignore(".claude/commands/test-agent.md")

    def test_agents_directory_whitelisted(self):
        """PR #126's .gitignore change also whitelisted .claude/agents/
        (no contents yet, but the project may add agent definitions
        later). Pin the whitelist so a future cleanup doesn't drop it."""
        text = (REPO / ".gitignore").read_text(encoding="utf-8")
        assert re.search(
            r"^!\.claude/agents/", text, re.MULTILINE
        ), (
            ".gitignore no longer whitelists .claude/agents/ — PR #126 "
            "added this for future shared-agent definitions."
        )

    def test_cache_directory_still_ignored(self):
        """The whole point of the .claude/* + whitelist pattern (rather
        than just removing the .claude/ ignore) is that per-clone state
        — cache/, scheduled_tasks.lock, projects/, settings.local.json —
        stays ignored. Pin one representative case so a future
        whitelist drift can't accidentally start tracking cache."""
        assert self._check_ignore(".claude/cache/some-cache-file"), (
            ".claude/cache/* is no longer ignored — per-clone state "
            "will pollute git status. Whitelist drifted too wide."
        )


# ---------------------------------------------------------------------------
# CLAUDE.md was refactored to point at the slash command
# ---------------------------------------------------------------------------


class TestClaudeMdProdSection:
    """PR #126 (and PR #125 for dev/test) refactored CLAUDE.md from
    inline-procedure to contract + slash-command source-of-truth.
    Pin that the prod section follows the same shape so the three
    sections stay consistent."""

    @classmethod
    def setup_class(cls):
        cls.claude_md = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

    def test_prod_section_mentions_slash_command(self):
        """The "autonomous-prod (release + smoke operator)" section
        should reference /prod-agent — if it drops the reference,
        readers won't find the procedure file."""
        # The section heading after the refactor.
        assert "/prod-agent" in self.claude_md, (
            "CLAUDE.md no longer references /prod-agent — readers won't "
            "find the procedure file the section now defers to."
        )

    def test_no_run_prod_natural_language_trigger(self):
        """PR #126 deliberately replaced the "run prod" natural-language
        trigger with the /prod-agent slash command (because the natural
        language trigger got lost on tree moves — same incident class).
        If "run prod" comes back, the regression to natural-language
        invocation is what made the procedure go missing before."""
        # Allow the phrase to appear in historical / changelog contexts
        # — what we're pinning is that the agent table and section
        # heading don't use it.
        prod_table_row_pattern = (
            r"\*\*autonomous-prod\*\*.*?manual\s+(?:`)?([^`]+?)(?:`)?\s+from\s+user"
        )
        match = re.search(prod_table_row_pattern, self.claude_md, re.DOTALL)
        assert match, (
            "Could not locate the autonomous-prod row in the agents table"
        )
        trigger = match.group(1).strip()
        assert "/prod-agent" in trigger, (
            f"autonomous-prod's trigger is '{trigger}' — expected "
            "/prod-agent (replacement for 'run prod' per PR #126)."
        )
