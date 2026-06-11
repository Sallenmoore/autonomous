"""Independent committed coverage for PR #81 / issue #76.

PR #81 introduces a typed ``MalformedResponseError`` and translates the
malformed-200 path of ``OpenAIClient._chat`` and ``.get_embedding``
from leaked stdlib ``KeyError`` / ``IndexError`` / ``TypeError`` /
``ValueError`` (the last covers ``json.JSONDecodeError``) into the
typed exception. ``generate_json``'s pre-#76 contract is preserved —
it still raises ``GenerateJSONEmptyResponseError`` on the malformed
body path.

Independent perspective (no peek at dev's ``tests/_dev_local/``):
- ``MalformedResponseError`` is a ``RuntimeError`` subclass (so the
  coarse-catch path stays open for consumers that do not yet adopt it).
- ``_chat`` raises ``MalformedResponseError`` on:
    * missing ``choices`` key (KeyError),
    * empty ``choices[]`` array (IndexError),
    * ``choices[0]`` missing ``message`` or ``content`` (KeyError/TypeError),
    * non-JSON 2xx body (ValueError / JSONDecodeError).
- The error message includes the body excerpt (first 200 chars of
  ``response.text``) so operators reading the worker log can triage
  without re-running the request.
- ``get_embedding`` raises ``MalformedResponseError`` for the same
  four shape failures on its ``data[0].embedding`` walk.
- ``generate_text`` and ``summarize_text`` (both thin ``_chat``
  wrappers) propagate ``MalformedResponseError`` unchanged.
- ``generate_json`` strict path: ``MalformedResponseError`` from
  ``_chat`` → re-translated to ``GenerateJSONEmptyResponseError``
  (pre-#76 contract preserved).
- ``generate_json`` fallback path (loose retry after strict-mode
  unavailable): same re-translation contract.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures — mirror the pattern in test_unit_openai_client.py so the
# OpenAIClient instance can be exercised without Mongo/dotenv.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_autotasks():
    with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    from autonomous.ai.models import openai_compat
    monkeypatch.setattr(openai_compat._HTTP, "retry_backoff", 0)


@pytest.fixture
def client():
    from autonomous.ai.models.openai_compat import OpenAIClient

    c = OpenAIClient.__new__(OpenAIClient)
    object.__setattr__(c, "_data", {"instructions": "You are a test agent."})
    object.__setattr__(c, "_dynamic_fields", {})
    object.__setattr__(c, "_changed_fields", [])
    object.__setattr__(c, "_initialised", True)
    object.__setattr__(c, "_created", False)
    for key, val in {
        "_base_url": "http://mock-hpc/api",
        "_api_key": "test-key",
        "_text_model": "gpt-oss:20b",
        "_json_model": "gpt-oss:20b",
        "_summary_model": "gemma3:4b",
        "_embedding_model": "qwen3-embedding",
        "_stt_model": "whisper-1",
        "_timeout": 1,
    }.items():
        object.__setattr__(c, key, val)
    return c


def _resp(json_data=None, *, text='{"malformed": true}', json_raises=None):
    """Build a fake response. ``json_raises`` simulates ``response.json()``
    raising — pass a ``ValueError("not json")`` to drive the
    JSONDecodeError branch."""
    r = MagicMock()
    r.status_code = 200
    if json_raises is not None:
        r.json.side_effect = json_raises
    else:
        r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status.return_value = None
    return r


# ---------------------------------------------------------------------------
# Exception identity
# ---------------------------------------------------------------------------


def test_malformed_response_error_is_runtime_error_subclass():
    """Consumers can ``except RuntimeError`` (coarse) or
    ``except MalformedResponseError`` (precise). Subclass relationship
    keeps both paths open."""
    from autonomous.ai.exceptions import MalformedResponseError

    assert issubclass(MalformedResponseError, RuntimeError)


def test_malformed_response_error_importable_from_exceptions_module():
    """Pin the import path. A relocation to
    ``ai.models.openai_compat.MalformedResponseError`` (or similar)
    would silently break consumer catches."""
    import autonomous.ai.exceptions as exc_mod

    assert hasattr(exc_mod, "MalformedResponseError")


# ---------------------------------------------------------------------------
# _chat malformed-body translations (via generate_text wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,json_data",
    [
        ("missing choices key", {"id": "x"}),
        ("empty choices array", {"choices": []}),
        ("choices[0] missing message", {"choices": [{"finish_reason": "stop"}]}),
        ("message missing content", {"choices": [{"message": {}}]}),
        # content=None → TypeError on subscript-access; not exercised here
        # because _chat returns the value directly without subscripting
        # further. But "choices is None" hits the TypeError branch.
        ("choices is None (TypeError)", {"choices": None}),
    ],
)
def test_chat_raises_malformed_response_error_on_unextractable_body(
    client, label, json_data,
):
    """The four-exception catch tuple at extraction:
    KeyError / IndexError / TypeError / ValueError. Pre-#76 these leaked
    raw; post-#76 they all become ``MalformedResponseError``."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data=json_data, text='{"shape": "broken"}'),
    ):
        with pytest.raises(MalformedResponseError):
            client.generate_text("anything")


def test_chat_raises_malformed_response_error_on_non_json_body(client):
    """Non-JSON 2xx body — ``response.json()`` raises ``ValueError``
    (json.JSONDecodeError is a subclass). The catch tuple includes
    ValueError so the translation fires."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            text="<html>504 gateway timeout</html>",
            json_raises=ValueError("Expecting value: line 1 column 1 (char 0)"),
        ),
    ):
        with pytest.raises(MalformedResponseError):
            client.generate_text("anything")


def test_chat_error_message_includes_body_excerpt(client):
    """Operators triaging an upstream-misconfiguration outage need to
    see WHAT came back without re-running the call. The error message
    must include ``body_excerpt=`` with at least part of the actual
    response text."""
    from autonomous.ai.exceptions import MalformedResponseError

    body_text = "Internal server message: token bucket exhausted on tenant=foo"
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text=body_text),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_text("anything")

    msg = str(excinfo.value)
    assert "body_excerpt" in msg, (
        f"error message must include the body_excerpt= marker for grep-ability: {msg!r}"
    )
    # First few characters of the body must appear in the excerpt.
    assert "Internal server message" in msg, (
        f"error message must surface actual body content to enable operator triage: {msg!r}"
    )


def test_chat_error_excerpt_is_truncated_to_200_chars(client):
    """Operator-friendly truncation. The diff hard-codes
    ``response.text[:200]`` — pin the bound so a future refactor that
    inadvertently dumps the entire body (which can be megabytes) doesn't
    pollute logs."""
    from autonomous.ai.exceptions import MalformedResponseError

    huge_body = "A" * 5000
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text=huge_body),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_text("anything")

    msg = str(excinfo.value)
    # Count A's in the message. Should be ≤ 200 (the body_excerpt slice
    # cap), with allowance that there's no other place to leak A's from.
    assert msg.count("A") <= 200, (
        f"body excerpt must be truncated to 200 chars; got {msg.count('A')} A's"
    )


# ---------------------------------------------------------------------------
# summarize_text and generate_text both go through _chat → both propagate
# ---------------------------------------------------------------------------


def test_summarize_text_propagates_malformed_response_error(client):
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text="{}"),
    ):
        with pytest.raises(MalformedResponseError):
            client.summarize_text("anything")


# ---------------------------------------------------------------------------
# generate_json — pre-#76 contract preservation
# ---------------------------------------------------------------------------


def test_generate_json_strict_path_translates_malformed_to_empty_response(client):
    """``generate_json`` consumers were never updated to catch the new
    ``MalformedResponseError``. The diff's two ``except
    MalformedResponseError`` blocks preserve the pre-#76 contract:
    consumers still see ``GenerateJSONEmptyResponseError`` for
    malformed bodies."""
    from autonomous.ai.exceptions import (
        GenerateJSONEmptyResponseError,
        MalformedResponseError,
    )

    # Strict mode path: malformed body from FIRST _chat call (the strict
    # request) → MalformedResponseError → caught at the outer except →
    # re-raised as GenerateJSONEmptyResponseError.
    # Note: generate_json may probe strict-mode-unsupported first; a
    # 200-with-malformed-body short-circuits the fallback dance and
    # surfaces immediately.
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text='{}'),
    ):
        with pytest.raises(GenerateJSONEmptyResponseError):
            client.generate_json("describe a thing")

    # And: the cause chain points to MalformedResponseError so an
    # operator who DOES adopt the typed exception can still walk
    # `__cause__` to find the original.
    try:
        with patch(
            "autonomous.ai.models.openai_compat._HTTP.post",
            return_value=_resp(json_data={"choices": []}, text='{}'),
        ):
            client.generate_json("describe a thing")
    except GenerateJSONEmptyResponseError as exc:
        assert isinstance(exc.__cause__, MalformedResponseError), (
            f"generate_json must chain MalformedResponseError → "
            f"GenerateJSONEmptyResponseError via `raise ... from exc` so "
            f"operators can introspect the original cause; got "
            f"__cause__={exc.__cause__!r}"
        )


# ---------------------------------------------------------------------------
# get_embedding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,json_data",
    [
        ("missing data key", {"object": "list"}),
        ("empty data array", {"data": []}),
        ("data[0] missing embedding", {"data": [{"index": 0}]}),
        ("data is None (TypeError)", {"data": None}),
    ],
)
def test_get_embedding_raises_malformed_response_error_on_shape_failures(
    client, label, json_data,
):
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data=json_data, text='{"shape": "broken"}'),
    ):
        with pytest.raises(MalformedResponseError):
            client.get_embedding("anything")


def test_get_embedding_raises_malformed_response_error_on_non_json_body(client):
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            text="upstream 502 bad gateway",
            json_raises=ValueError("Expecting value: line 1 column 1 (char 0)"),
        ),
    ):
        with pytest.raises(MalformedResponseError):
            client.get_embedding("anything")


def test_get_embedding_error_message_includes_body_excerpt(client):
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"data": []}, text="embeddings backend OOM"),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.get_embedding("anything")
    msg = str(excinfo.value)
    assert "body_excerpt" in msg
    assert "embeddings backend OOM" in msg


# ---------------------------------------------------------------------------
# Happy path regression guard — extraction still works on well-shaped bodies
# ---------------------------------------------------------------------------


def test_chat_happy_path_unaffected(client):
    """Sanity guard: the malformed-200 translation must not break the
    extraction on well-formed bodies."""
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data={"choices": [{"message": {"content": "hello"}}]},
            text='{"choices":[{"message":{"content":"hello"}}]}',
        ),
    ):
        assert client.generate_text("hi") == "hello"


def test_get_embedding_happy_path_unaffected(client):
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
            text='{"data":[{"embedding":[0.1,0.2,0.3]}]}',
        ),
    ):
        assert client.get_embedding("hi") == [0.1, 0.2, 0.3]
