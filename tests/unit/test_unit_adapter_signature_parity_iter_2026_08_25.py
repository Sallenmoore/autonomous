"""Adapter/agent signature parity + smoke-test cold-resolve guards.

Two failure modes that shipped undetected and are cheap to pin.

**#242 — adapter drift.** ``MockAIModel.generate_audio`` sat at
``(prompt, voice=None)`` while every real adapter and the caller
``AudioAgent.generate`` used ``(prompt, voice_description=None,
voice_id=None)``. Selecting the mock for TTS raised ``TypeError``.
Nothing caught it because ``generate_audio`` is deliberately outside
``AIModelProtocol`` (see ``openai_compat.py``: "generate_audio is not in
AIModelProtocol (slice 1 scope)"), so the conformance suite never looks
at it. This guards the property that actually matters — *every adapter
in the registry accepts the kwargs the agents actually pass it* —
without requiring the protocol to grow.

**#244 — smoke test cold resolve.** ``scripts/smoke_test.sh`` must
install with ``--no-cache-dir``: pip caches the simple-index page, so a
run racing the upload caches a listing without the new version and
every retry then fails against the cache rather than PyPI.
"""

import inspect
import re
from pathlib import Path

import pytest

from autonomous.ai.baseagent import BaseAgent

# The kwargs each agent entry point actually passes its client. Sourced
# from the call sites, not from any adapter — the point is to catch an
# adapter that drifted AWAY from what the agents send.
#   textagent.py     generate / summarize_text
#   jsonagent.py     generate
#   audioagent.py    generate / transcribe / dramatize
#   imageagent.py    generate
AGENT_CALL_KWARGS = {
    "generate_text": [
        "additional_instructions",
        "uri",
        "context",
        "system_prompt",
        "model",
        "temperature",
    ],
    "summarize_text": ["primer", "model"],
    "generate_json": [
        "system_prompt",
        "uri",
        "context",
        "json_schema",
        "schema_name",
        "model",
        "temperature",
    ],
    "generate_audio": ["voice_description", "voice_id"],
    "generate_image": ["negative_prompt", "aspect_ratio", "files", "style"],
}


def _adapters_implementing(method):
    for provider, cls in sorted(BaseAgent.MODEL_REGISTRY.items()):
        fn = getattr(cls, method, None)
        if fn is None:
            continue
        params = inspect.signature(fn).parameters
        # A **kwargs sink absorbs anything — nothing to check. This is
        # how openai_compat's typed unsupported-routing stubs are shaped.
        if any(p.kind is p.VAR_KEYWORD for p in params.values()):
            continue
        yield provider, cls, params


class TestAdapterAcceptsWhatAgentsPass:
    @pytest.mark.parametrize("method,kwargs", sorted(AGENT_CALL_KWARGS.items()))
    def test_every_registry_adapter_accepts_the_agents_kwargs(self, method, kwargs):
        drifted = []
        for provider, cls, params in _adapters_implementing(method):
            missing = [k for k in kwargs if k not in params]
            if missing:
                drifted.append(f"{provider}/{cls.__name__}.{method} missing {missing}")
        assert not drifted, (
            "adapter signature drifted from what the agents call it with — "
            "selecting this provider raises TypeError at runtime: "
            + "; ".join(drifted)
        )

    def test_the_guard_can_actually_fail(self):
        # A guard that cannot fail is decoration. Reproduce #242's exact
        # shape and confirm the check catches it.
        class _Drifted:
            def generate_audio(self, prompt, voice=None):
                pass

        params = inspect.signature(_Drifted.generate_audio).parameters
        missing = [k for k in AGENT_CALL_KWARGS["generate_audio"] if k not in params]
        assert missing == ["voice_description", "voice_id"]

    def test_mock_adapter_is_selectable_for_every_agent_method(self):
        # The mock is what a consumer reaches for to exercise their BYOK
        # wiring without spending credits — #239 made that a per-call
        # option. If it can't serve a method the agents call, the first
        # thing a new consumer does raises.
        from autonomous.ai.models.mock_model import MockAIModel

        for method, kwargs in AGENT_CALL_KWARGS.items():
            fn = getattr(MockAIModel, method, None)
            assert fn is not None, f"MockAIModel lacks {method}"
            params = inspect.signature(fn).parameters
            if any(p.kind is p.VAR_KEYWORD for p in params.values()):
                continue
            missing = [k for k in kwargs if k not in params]
            assert not missing, f"MockAIModel.{method} missing {missing}"


class TestSmokeTestResolvesCold:
    """#244. pip caches the simple-index page; a smoke run seconds after
    an upload caches a listing without the new version, and the retry
    loop then re-asks the cache instead of PyPI — turning a race into a
    persistent false 'released and immediately broken'."""

    @staticmethod
    def _script():
        path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.sh"
        assert path.is_file(), f"missing {path}"
        return path.read_text()

    def test_every_package_install_bypasses_the_cache(self):
        script = self._script()
        installs = []
        for raw in script.splitlines():
            line = raw.strip()
            # Real commands only — the script also names the install in a
            # comment and in its failure message, and neither installs
            # anything.
            if line.startswith("#") or line.startswith("echo "):
                continue
            if re.search(r"pip install .*autonomous-app", line):
                installs.append(line)
        assert installs, "no autonomous-app install found in smoke_test.sh"
        cached = [line for line in installs if "--no-cache-dir" not in line]
        assert not cached, (
            "smoke_test.sh must resolve cold — pip caches the index page, so "
            "these installs can replay a pre-release listing on every retry: "
            + "; ".join(cached)
        )

    def test_both_install_paths_are_covered(self):
        # Host-venv and container paths install separately; a fix applied
        # to only one leaves the other able to drift back.
        script = self._script()
        assert script.count("--no-cache-dir") >= 2, (
            "expected the cache bypass on both the host-venv and container "
            "install paths"
        )
