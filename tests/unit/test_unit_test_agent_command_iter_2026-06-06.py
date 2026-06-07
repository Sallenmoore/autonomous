"""Coverage for the /test-agent thin-dispatcher conversion (commit f093772,
landed in this bundle).

Symmetric with ``test_unit_prod_agent_command_iter_2026_05_25.py``: the
``.claude/commands/test-agent.md`` slash command was converted to a thin
dispatcher that references the shared template at
``/opt/stacks/agent-runner/templates/test-agent.md`` and injects autonomous's
project values. The procedure prose lives in that out-of-repo template
(absent in CI's clean checkout), so this repo can only pin the dispatcher's
*delegation contract* and the project values it hands the template.

The prod-agent dispatcher already had a command-file test; the test-agent
dispatcher (converted in the same wave) had none — a coverage asymmetry the
test→main review flagged. This closes it. If a future tree move or edit drops
the dispatcher or its delegation, the procedure becomes "whatever Claude
remembers today" — the exact regression class the slash-command split was
meant to prevent.

Hermetic: filesystem reads + a ``git check-ignore`` subprocess. No GitHub /
PyPI / network.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
COMMANDS = REPO / ".claude" / "commands"


class TestTestAgentCommandFile:
    def test_command_file_exists(self):
        path = COMMANDS / "test-agent.md"
        assert path.exists(), (
            ".claude/commands/test-agent.md is missing — the /test-agent "
            "slash command must be tracked so it survives tree moves."
        )

    def test_has_yaml_frontmatter_with_description(self):
        text = (COMMANDS / "test-agent.md").read_text(encoding="utf-8")
        match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        assert match, "test-agent.md is missing the YAML frontmatter block"
        assert re.search(r"^description:\s*\S", match.group(1), re.MULTILINE), (
            "test-agent.md frontmatter has no description: line"
        )

    def test_dispatcher_delegates_to_shared_template(self):
        """A thin dispatcher must name the canonical template and tell the
        agent to read + execute it. Losing this reference makes the
        procedure unreachable."""
        text = (COMMANDS / "test-agent.md").read_text(encoding="utf-8")
        assert "templates/test-agent.md" in text, (
            "/test-agent dispatcher no longer references the shared template "
            "— the procedure becomes unreachable."
        )
        assert re.search(r"\bRead that file\b", text) and "execute it" in text, (
            "/test-agent dispatcher no longer instructs the agent to read + "
            "execute the referenced template."
        )

    def test_core_project_values_declared(self):
        """The dispatcher hands the shared template autonomous's identity +
        branch topology. If these drift, the template drives the wrong repo
        or branches."""
        text = (COMMANDS / "test-agent.md").read_text(encoding="utf-8")
        assert re.search(r"PROJECT\s*=\s*autonomous", text)
        assert "Sallenmoore/autonomous" in text
        for branch in ("BRANCH_DEV = dev", "BRANCH_TEST = test", "BRANCH_MAIN = main"):
            assert branch in text, f"/test-agent dispatcher dropped '{branch}'"

    def test_sentinel_driver_declared(self):
        """PROJECT_UPPER drives the AUTONOMOUS_CYCLE: sentinel the cycle
        orchestrator gates the prod deploy on. If it drifts, the machine
        handoff token changes and the orchestrator stops recognizing it."""
        text = (COMMANDS / "test-agent.md").read_text(encoding="utf-8")
        assert re.search(r"PROJECT_UPPER\s*=\s*AUTONOMOUS", text), (
            "/test-agent dispatcher dropped PROJECT_UPPER = AUTONOMOUS — the "
            "AUTONOMOUS_CYCLE: deploy sentinel would no longer be emitted."
        )


class TestTestAgentCommandTracked:
    def _check_ignore(self, path: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", path],
            check=False,
        )
        return result.returncode == 0

    def test_command_not_ignored(self):
        assert not self._check_ignore(".claude/commands/test-agent.md"), (
            ".claude/commands/test-agent.md is ignored by git — the .gitignore "
            "whitelist is too narrow; /test-agent will be lost on the next "
            "tree move."
        )
