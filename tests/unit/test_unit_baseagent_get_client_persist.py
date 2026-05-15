"""Behavioral pin: BaseAgent.get_client(persist=...) controls whether
the provider-switch path persists to DB.

Default behavior (persist=True) is the legacy "save client + save self"
path. persist=False skips both saves — for in-memory-only construction
in tests or throughput-sensitive callers that will save() themselves.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.ai import baseagent
from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.models.mock_model import MockAIModel


class _StubAgent:
    """A minimal stand-in that has just enough surface for get_client.

    Bypasses AutoModel construction (which needs a Mongo connection)
    by calling get_client as an unbound method with a hand-built self.
    Inherits BaseAgent's MODEL_REGISTRY by class-level reference so
    monkeypatch.setitem(BaseAgent.MODEL_REGISTRY, ...) applies.
    """

    MODEL_REGISTRY = BaseAgent.MODEL_REGISTRY

    def __init__(self, provider="mock"):
        self.provider = provider
        self.name = "stub"
        self.instructions = ""
        self.description = ""
        self.client = None
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


def _make_client_class():
    """Return a class with a .save() counter for inspection."""
    saves = []

    class _ClientWithCounter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def save(self):
            saves.append(self)

        def delete(self):
            pass

    return _ClientWithCounter, saves


def test_persist_default_saves_both(monkeypatch):
    """persist=True (default) → client.save() + self.save() both fire."""
    client_cls, client_saves = _make_client_class()
    monkeypatch.setitem(BaseAgent.MODEL_REGISTRY, "mock", client_cls)

    agent = _StubAgent(provider="mock")
    BaseAgent.get_client(agent)

    assert len(client_saves) == 1, "client.save() must fire on provider switch"
    assert agent.save_calls == 1, "agent.save() must fire on provider switch"


def test_persist_false_skips_both(monkeypatch):
    """persist=False → neither save fires; caller takes responsibility."""
    client_cls, client_saves = _make_client_class()
    monkeypatch.setitem(BaseAgent.MODEL_REGISTRY, "mock", client_cls)

    agent = _StubAgent(provider="mock")
    BaseAgent.get_client(agent, persist=False)

    assert client_saves == [], (
        "client.save() must NOT fire when persist=False — caller is "
        "responsible for the next save"
    )
    assert agent.save_calls == 0, "agent.save() must NOT fire when persist=False"
    # But the client itself must still be set so the in-memory agent works.
    assert isinstance(agent.client, client_cls)


def test_persist_false_skips_delete_of_old_client(monkeypatch):
    """persist=False must NOT delete the old client doc.

    A delete-without-save would leave self.client pointing at a
    destroyed doc — worse than the orphan-doc trade-off the contract
    documents. Pin that delete is skipped in lockstep with the save
    skip on the provider-switch path.
    """
    new_client_cls, _ = _make_client_class()
    monkeypatch.setitem(BaseAgent.MODEL_REGISTRY, "openai", new_client_cls)

    # Build an agent with an EXISTING wrong-type client (the
    # provider-switch path). The old client tracks delete() calls so
    # we can verify it's not called when persist=False.
    deletes = []

    class _OldClient:
        def delete(self):
            deletes.append(1)

    agent = _StubAgent(provider="openai")
    agent.client = _OldClient()

    BaseAgent.get_client(agent, persist=False)

    assert deletes == [], (
        "persist=False must NOT delete the old client doc; the orphan "
        "trade-off is intentional per the docstring"
    )
    assert isinstance(agent.client, new_client_cls), (
        "the in-memory client reference is still updated to the new type"
    )


def test_persist_true_still_deletes_old_client(monkeypatch):
    """Negative pin: persist=True (default) preserves legacy delete behavior."""
    new_client_cls, _ = _make_client_class()
    monkeypatch.setitem(BaseAgent.MODEL_REGISTRY, "openai", new_client_cls)

    deletes = []

    class _OldClient:
        def delete(self):
            deletes.append(1)

    agent = _StubAgent(provider="openai")
    agent.client = _OldClient()

    BaseAgent.get_client(agent)  # persist=True default

    assert deletes == [1], (
        "persist=True must continue to delete the old client doc — "
        "this is the legacy behavior that callers depend on"
    )


def test_persist_kwarg_is_keyword_only():
    """persist must be keyword-only — guards against positional misuse."""
    # The signature is `def get_client(self, provider=None, *, persist=True)`.
    # Passing two positionals should fail.
    agent = _StubAgent(provider="mock")
    with pytest.raises(TypeError):
        # noqa: extra-positional intentionally — confirm * separator works
        BaseAgent.get_client(agent, None, False)
