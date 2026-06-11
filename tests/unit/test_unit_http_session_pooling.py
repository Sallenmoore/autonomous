"""Behavioral pin: each AI-stack module uses its module-level pooled
HTTP seam (a ``requests.Session`` directly, or an ``HttpClient`` that
holds one), not bare ``requests.post``.

Catches a regression that would silently un-do the connection-pooling
optimization (someone reverts a single line back to `requests.post(...)`).
Detection is via monkeypatching: replace the module-level seam's ``post``
with a counter and ``requests.post`` with another counter, invoke a
method, assert the seam was used and the bare module-level was not.

Per-module seam (kept on this file so a future migration only edits the
one test it touches):
- ``openai_compat._SESSION`` — direct ``requests.Session``
- ``db_sync._HTTP_SESSION`` — direct ``requests.Session``
- ``local_model._HTTP`` — ``autonomous.http.HttpClient`` (migrated #50 slice C)
"""

from unittest.mock import MagicMock

import pytest
import requests

from autonomous.ai.models import openai_compat, local_model
from autonomous.db import db_sync


def _stub_response(status=200, json_body=None, content=b""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.content = content
    r.text = ""
    r.raise_for_status.return_value = None
    return r


def test_openai_compat_uses_session_not_bare_requests(monkeypatch):
    session_post = MagicMock(return_value=_stub_response(json_body={"data": [{"embedding": [0.0]}]}))
    bare_post = MagicMock()
    monkeypatch.setattr(openai_compat._SESSION, "post", session_post)
    monkeypatch.setattr(requests, "post", bare_post)

    client = openai_compat.OpenAIClient.__new__(openai_compat.OpenAIClient)
    object.__setattr__(client, "_base_url", "http://stub")
    object.__setattr__(client, "_api_key", "k")
    object.__setattr__(client, "_embedding_model", "m")
    object.__setattr__(client, "_timeout", 1)
    object.__setattr__(client, "_retry_attempts", 1)
    object.__setattr__(client, "_retry_backoff", 0)
    client.get_embedding("text")

    assert session_post.call_count == 1
    assert bare_post.call_count == 0


def test_db_sync_get_vector_local_uses_session(monkeypatch):
    session_post = MagicMock(return_value=_stub_response(json_body={"embedding": [0.0]}))
    bare_post = MagicMock()
    monkeypatch.setattr(db_sync._HTTP_SESSION, "post", session_post)
    monkeypatch.setattr(requests, "post", bare_post)

    result = db_sync._get_vector_local("text")
    assert result == [0.0]
    assert session_post.call_count == 1
    assert bare_post.call_count == 0


def test_local_model_flush_memory_uses_session(monkeypatch):
    # Post-#50-slice-C the local_model seam is HttpClient, not a bare
    # Session. The intent of this test is unchanged — verify the
    # pooled-HTTP path is used rather than bare ``requests.post`` —
    # but the patch target moves from ``_SESSION.post`` to
    # ``_HTTP.post`` (HttpClient.post routes through its internal
    # ``self.session.request``, so patching ``_HTTP.session.post``
    # would no-op).
    http_post = MagicMock(return_value=_stub_response())
    bare_post = MagicMock()
    monkeypatch.setattr(local_model._HTTP, "post", http_post)
    monkeypatch.setattr(requests, "post", bare_post)

    model = local_model.LocalAIModel.__new__(local_model.LocalAIModel)
    object.__setattr__(model, "_ollama_url", "http://stub")
    model.flush_memory("anything")

    assert http_post.call_count == 1
    assert bare_post.call_count == 0
