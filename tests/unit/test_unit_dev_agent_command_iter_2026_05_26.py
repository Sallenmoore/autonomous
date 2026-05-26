"""Independent coverage for PR #2 (chore: complete Forgejo cutover for
autonomous-dev tree).

PR #2 adds ``.claude/commands/dev-agent.md`` as a tracked file in the
canonical repo, bumps the GitHub Actions ``actions/setup-python`` pin
from ``v3`` to ``v5`` so the self-hosted Forgejo runner can satisfy
the action's Node 20 baseline, and tightens a handful of phrases in
CLAUDE.md (direct issues URL, single source for the three-agent
slash-command preamble, "audit layer" wording).

The dev-perspective on this work is "I moved /dev-agent into the tree
the same way /test-agent and /prod-agent already were, and aligned
CLAUDE.md wording with the migration." The test agent's independent
perspective is "are the things this PR promised actually present, are
the things the PR promised to delete actually gone, and would the
gitignore whitelist + workflow pin survive the next tree move?"

Hermetic: filesystem reads + ``git check-ignore`` subprocesses + a
single ``yaml.safe_load`` of the workflow file (already a hard dep of
the docs build). No GitHub or PyPI calls.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
COMMANDS = REPO / ".claude" / "commands"


# ---------------------------------------------------------------------------
# The /dev-agent slash command file exists with the expected shape
# ---------------------------------------------------------------------------


class TestDevAgentCommandFile:
    """The new file is the headline of PR #2. If it's missing, the
    dev-agent procedure goes back to "whatever Claude remembers about
    /opt/projects/autonomous-dev/.claude/commands/dev-agent.md", which
    is the exact failure mode the test-agent + prod-agent migrations
    were already meant to close."""

    @classmethod
    def setup_class(cls):
        cls.path = COMMANDS / "dev-agent.md"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.exists() else ""

    def test_command_file_exists(self):
        assert self.path.exists(), (
            ".claude/commands/dev-agent.md is missing — PR #2 promised "
            "to add the /dev-agent slash command to the canonical repo "
            "(it previously lived only in /opt/projects/autonomous-dev/)."
        )

    def test_has_yaml_frontmatter_with_description(self):
        """Same shape as the sibling /test-agent and /prod-agent
        commands — markdown body gated by a YAML frontmatter block
        whose only required field is ``description``."""
        match = re.match(r"---\n(.*?)\n---\n", self.text, re.DOTALL)
        assert match, "dev-agent.md is missing the YAML frontmatter block"
        frontmatter = match.group(1)
        assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE), (
            "dev-agent.md frontmatter has no description: line"
        )

    def test_no_loop_or_polling_instruction(self):
        """Per CLAUDE.md the dev agent is manual-invocation only — the
        procedure must explicitly forbid wrapping itself in ``/loop`` or
        re-arming via ``ScheduleWakeup``/``CronCreate``/``Monitor``. If
        a future edit accidentally invites looping, the agent topology's
        cadence invariants collapse."""
        # Either the explicit "runs once per call" framing or any of the
        # "do not [wrap in / suggest] /loop" forms keeps the no-loop
        # invariant readable.
        assert re.search(
            r"\bruns? once per call\b|"
            r"\bDo NOT (?:wrap in|suggest|loop\b)\s*`?/?loop`?|"
            r"\bDo NOT loop\b",
            self.text,
            re.IGNORECASE,
        ), (
            "/dev-agent procedure lost every recognisable form of the "
            "no-loop instruction (neither 'runs once per call' nor any "
            "'Do NOT … /loop' phrasing survives)."
        )
        assert re.search(
            r"ScheduleWakeup.*CronCreate.*Monitor|"
            r"Do NOT call `ScheduleWakeup`",
            self.text,
            re.DOTALL,
        ), (
            "/dev-agent procedure lost the explicit "
            "ScheduleWakeup/CronCreate/Monitor prohibition"
        )

    def test_no_gh_invocations(self):
        """Regression guard: the entire point of the 2026-05-26 Forgejo
        cutover is "all ``gh`` invocations have been replaced by
        ``curl`` against the Forgejo API." If a ``gh issue create`` /
        ``gh pr create`` etc. ever comes back, the dev agent is talking
        to the stale public github mirror, not the canonical Forgejo
        tracker."""
        # Without this guard, a deleted dev-agent.md returns "" from
        # setup_class and the offender regex finds nothing — the test
        # would pass vacuously. The neighbouring test_command_file_exists
        # already fails on deletion, but pinning the non-empty
        # invariant here makes this test's coverage stand on its own.
        assert self.text, (
            "dev-agent.md is missing or unreadable — gh-absence claim "
            "is vacuous without a body to check."
        )
        offenders = re.findall(r"(?m)^\s*gh\s+(?:issue|pr|repo|api|run)\b.*$", self.text)
        assert offenders == [], (
            "dev-agent.md re-introduces gh CLI invocations:\n" +
            "\n".join(offenders) +
            "\n\nThese must be curl-against-Forgejo, per the doc's "
            "stated 'do not call gh for any reason' contract."
        )

    def test_forgejo_canonical_base_url_documented(self):
        """The curl preamble must anchor on the canonical Forgejo URL.
        If the URL drifts (e.g. to a misspelling, or back to the github
        API host), every subsequent curl in the procedure breaks
        silently — Forgejo and github both accept ``Authorization:
        token <x>`` so the agent would just get 401s with a confusing
        host."""
        expected = "https://git.stevenamoore.dev/api/v1/repos/samoore/autonomous"
        assert expected in self.text, (
            f"dev-agent.md no longer references the canonical Forgejo "
            f"base URL {expected!r} — the curl preamble has nothing to "
            "anchor on."
        )

    def test_label_id_vs_name_quirk_documented(self):
        """The Forgejo POST endpoints want integer label IDs while GET
        list endpoints accept label names — this asymmetry has bitten
        every cutover (storyteller, autonomous-test, autonomous-prod).
        Pin that the dev agent's preamble preserves the warning so a
        future trim doesn't drop it."""
        assert "LABEL_MAP" in self.text, (
            "dev-agent.md no longer defines the LABEL_MAP name→id "
            "convenience — the API-quirk knowledge that POST takes IDs "
            "will be relearned the next time it bites."
        )

    def test_back_merge_first_rule_present(self):
        """The "back-merge FIRST" invariant is what prevents the dev
        agent from cutting a new batch branch off a stale dev tip and
        re-introducing regressions that the test agent already fixed.
        Promoted to step 1 of the procedure on 2026-05-16; pin the
        promotion so a refactor doesn't silently demote it."""
        assert re.search(
            r"Back-merge FIRST|back-merge first", self.text, re.IGNORECASE
        ), (
            "/dev-agent procedure lost the 'back-merge first' invariant "
            "— the next iteration could branch off stale dev."
        )

    def test_dev_local_tests_marked_uncommitted(self):
        """The two-perspective testing design depends on dev's tests
        being gitignored (so the test agent works from the PR diff
        alone). If a future doc edit says "commit your tests/_dev_local
        tests" the structural-second-perspective invariant collapses
        into rubber-stamping."""
        # Allow flexible phrasing but require BOTH that tests/_dev_local
        # is mentioned AND that it's marked as not-committed somehow.
        assert "tests/_dev_local" in self.text, (
            "dev-agent.md no longer mentions tests/_dev_local — the "
            "ephemeral-test directory is invisible to the procedure."
        )
        assert re.search(
            r"do not commit|not committed|gitignored", self.text, re.IGNORECASE
        ), (
            "dev-agent.md no longer marks tests/_dev_local as "
            "uncommitted — the two-perspective invariant is at risk."
        )


# ---------------------------------------------------------------------------
# .gitignore whitelist must cover the new file
# ---------------------------------------------------------------------------


class TestDevAgentCommandTracked:
    """The same .gitignore-whitelist lesson that PR #126 codified for
    prod-agent.md applies here: the file must NOT be ignored, else the
    next tree move loses it (the exact incident that prompted the
    whitelist in the first place)."""

    @staticmethod
    def _check_ignore(path: str) -> bool:
        """Return True if ``path`` is currently ignored by git."""
        result = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", path],
            check=False,
        )
        # check-ignore -q: exit 0 if ignored, 1 if not ignored.
        return result.returncode == 0

    def test_dev_agent_command_not_ignored(self):
        assert not self._check_ignore(".claude/commands/dev-agent.md"), (
            ".claude/commands/dev-agent.md is ignored by git — the "
            ".gitignore whitelist is too narrow. /dev-agent will be lost "
            "on the next tree move, undoing PR #2."
        )

    def test_sibling_commands_still_tracked(self):
        """If a future .gitignore edit accidentally narrows the
        whitelist to just /dev-agent's directory shape, the sister
        commands go missing the same way. Pin both."""
        for sibling in ("test-agent.md", "prod-agent.md"):
            assert not self._check_ignore(f".claude/commands/{sibling}"), (
                f".claude/commands/{sibling} is ignored — whitelist "
                "regressed to a shape that drops sibling slash commands."
            )


# ---------------------------------------------------------------------------
# The setup-python workflow bump (v3 → v5)
# ---------------------------------------------------------------------------


class TestPythonPackageWorkflowSetupPython:
    """PR #2 bumps the setup-python action from v3 to v5 because the
    self-hosted Forgejo runner needs Node 20 (which v3 doesn't satisfy
    — it's stuck on Node 16). A silent rollback to v3 would put CI
    back into "Node 16 deprecation warning + occasional skip" state on
    this runner."""

    @classmethod
    def setup_class(cls):
        path = REPO / ".github" / "workflows" / "python-package.yml"
        cls.parsed = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Floors below codify "uses Node 20 or newer" — the runtime baseline
    # the self-hosted Forgejo runner provides. checkout@v3 / setup-python@v4
    # and earlier were Node 16 and emit deprecation warnings (or fail
    # outright depending on runner config). The action-major → minimum-Node
    # mapping is documented in each action's release notes; we pin the
    # major here rather than the Node version because the Node baseline
    # is what github surfaces as the action's deprecation criterion.
    _MIN_MAJOR = {
        "actions/setup-python": 5,
        "actions/checkout": 4,
    }

    @classmethod
    def _walk_uses(cls):
        for job in (cls.parsed.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                uses = step.get("uses", "")
                if uses.startswith("actions/"):
                    yield uses

    def test_setup_python_pinned_to_v5_or_higher(self):
        found = [u for u in self._walk_uses() if u.startswith("actions/setup-python@")]
        assert found, (
            "python-package.yml no longer uses actions/setup-python — "
            "the 2026-05-26 Forgejo cutover's whole point was to pin a "
            "Forgejo-runner-compatible version of that action."
        )
        for uses in found:
            version = uses.split("@", 1)[1]
            match = re.match(r"v(\d+)", version)
            assert match, (
                f"actions/setup-python pinned to non-version ref "
                f"{version!r} — can't verify it satisfies Forgejo runner "
                "requirements."
            )
            major = int(match.group(1))
            assert major >= self._MIN_MAJOR["actions/setup-python"], (
                f"actions/setup-python regressed to {uses!r}; the Forgejo "
                "cutover bumped to v5 because the self-hosted runner needs "
                "the Node-20-baseline version."
            )

    def test_checkout_pinned_to_v4_or_higher(self):
        """Same Node-20-baseline argument as setup-python: ``checkout@v3``
        is Node 16. The Forgejo cutover only touched setup-python because
        that was the action failing in the wild, but a future "let's
        roll the actions back" sweep would silently re-break the runner
        through checkout@v3. Pin the floor."""
        found = [u for u in self._walk_uses() if u.startswith("actions/checkout@")]
        assert found, (
            "python-package.yml no longer uses actions/checkout — every "
            "job needs it; missing means the workflow is broken."
        )
        for uses in found:
            version = uses.split("@", 1)[1]
            match = re.match(r"v(\d+)", version)
            assert match, (
                f"actions/checkout pinned to non-version ref {version!r} "
                "— can't verify Node-20 compatibility."
            )
            major = int(match.group(1))
            assert major >= self._MIN_MAJOR["actions/checkout"], (
                f"actions/checkout regressed to {uses!r}; the Forgejo "
                "self-hosted runner needs the Node-20-baseline (v4+) "
                "version. The setup-python bump alone is not sufficient."
            )


# ---------------------------------------------------------------------------
# CLAUDE.md wording updates
# ---------------------------------------------------------------------------


class TestClaudeMdForgejoCutover:
    """The CLAUDE.md edits in PR #2 are small but each removes a
    specific footgun. Pin each so a future copy-edit doesn't silently
    walk one back."""

    @classmethod
    def setup_class(cls):
        cls.text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

    def test_direct_forgejo_issues_url_present(self):
        """The storyteller-coordination bullet now points at the actual
        issues page URL, not just "Forgejo issues". Removing the URL
        means a reader has to guess what host/path to use — the github
        muscle-memory will fill that gap with the wrong host."""
        assert (
            "https://git.stevenamoore.dev/samoore/autonomous/issues"
            in self.text
        ), (
            "CLAUDE.md no longer carries the direct Forgejo issues URL "
            "— readers will fall back to whatever tracker their muscle "
            "memory suggests (typically the stale github mirror)."
        )

    def test_dev_agent_slash_command_referenced(self):
        """Forward-looking regression guard: ``/dev-agent`` appeared in
        the agents-at-a-glance table independently of this PR (the
        table predates the Forgejo cutover), so this test holds before
        and after the bundle. It still earns its keep — a future
        CLAUDE.md cleanup that drops the agents table or renames the
        command would break this pin and surface the regression."""
        assert "/dev-agent" in self.text, (
            "CLAUDE.md no longer references /dev-agent — the slash "
            "command has no entrypoint mention from the doctrine doc."
        )

    def test_issue_preamble_points_at_all_three_commands(self):
        """The issue-body-template preamble previously pointed at
        ``.claude/commands/test-agent.md`` alone. PR #2 generalises
        that to "matches the agent slash commands at
        ``.claude/commands/{dev,test,prod}-agent.md``" — if the
        generalisation regresses, the storyteller agent (the primary
        consumer of this template) sees only one of the three shapes."""
        assert re.search(
            r"\.claude/commands/\{dev,test,prod\}-agent\.md",
            self.text,
        ), (
            "CLAUDE.md no longer generalises the preamble reference "
            "across all three agent slash commands — the cross-link "
            "drifted back to a single-file pointer."
        )

    def test_github_mirror_explicitly_marked_stale(self):
        """The bullet now says "the legacy github tracker at
        Sallenmoore/autonomous is a stale public mirror only — do not
        file there." That explicit warning is the one thing that
        stops the storyteller agent from following the github URL
        google may surface first."""
        assert "stale public mirror" in self.text, (
            "CLAUDE.md no longer explicitly marks the github tracker "
            "as a stale public mirror — readers may not realise it is "
            "no longer the source of truth."
        )
