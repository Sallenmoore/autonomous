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
import requests


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


def test_chat_error_carries_body_excerpt_as_attribute(client):
    """Operators triaging an upstream-misconfiguration outage need to
    see WHAT came back without re-running the call. Post-#83 the body
    excerpt lives on the exception as ``.body_excerpt`` (structured
    attribute, not message-string substring) — same operator-triage
    intent as the pre-#83 ``body_excerpt=`` message marker, redirected
    to the new structured carrier. Endpoint and status round out the
    triage surface.

    Source and test were updated in the same patch (#83 restructured
    the constructor; the prior message-string assertion is no longer
    sound). Same source-and-test inseparability pattern as the #50
    HttpClient-migration slices."""
    from autonomous.ai.exceptions import MalformedResponseError

    body_text = "Internal server message: token bucket exhausted on tenant=foo"
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text=body_text),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_text("anything")

    exc = excinfo.value
    assert exc.body_excerpt.startswith("Internal server message"), (
        f"body_excerpt must surface actual response text for triage: "
        f"{exc.body_excerpt!r}"
    )
    assert exc.endpoint == "/chat/completions", (
        f"endpoint attribute must identify which path returned the "
        f"malformed body: {exc.endpoint!r}"
    )
    assert exc.status == 200, (
        f"status attribute must reflect the 2xx the endpoint actually "
        f"returned (malformed-200 case): {exc.status!r}"
    )


def test_chat_error_body_excerpt_is_truncated_to_200_chars(client):
    """Operator-friendly truncation. Post-#83 the 200-char bound lives
    in the ``MalformedResponseError`` constructor (``_EXCERPT_MAX``)
    rather than at each per-site raise — pin the bound where it
    actually lives so a future regression that changes the constant
    (or accidentally bypasses the constructor) goes red.

    Source and test were updated in the same patch — the pre-#83
    bound lived in an f-string at the raise site (``response.text[:200]``),
    and the test counted A's in the message. Post-#83 the bound lives
    in the constructor and the excerpt is an attribute. Same
    inseparability pattern as the #50 migration slices."""
    from autonomous.ai.exceptions import MalformedResponseError

    huge_body = "A" * 5000
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"choices": []}, text=huge_body),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_text("anything")

    exc = excinfo.value
    assert len(exc.body_excerpt) <= 200, (
        f"body_excerpt must be truncated to <=200 chars by the "
        f"constructor; got {len(exc.body_excerpt)}"
    )
    # And specifically — for the all-A body — the excerpt must be
    # exactly 200 A's (constructor truncated huge_body[:200]).
    assert exc.body_excerpt == "A" * 200, (
        f"body_excerpt must be the first 200 chars of response.text "
        f"(constructor enforces _EXCERPT_MAX=200): {exc.body_excerpt!r}"
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


def test_generate_json_loose_fallback_path_also_translates_malformed(client):
    """The §6 /review-pr coverage gap (pr-test-analyzer Important #3).

    ``generate_json`` has TWO ``except MalformedResponseError`` blocks:
    one for the strict-mode call (line ~469), one for the loose-mode
    retry after the strict probe failed (line ~462). The earlier test
    only exercises the strict path. Pin the LOOSE-FALLBACK path too —
    its re-translation produces a DIFFERENT diagnostic message
    (``"...error after fallback retry: ..."``), and an operator
    triaging logs distinguishes outage modes by that string. A refactor
    that collapsed the two catch blocks would silently lose the
    distinction with no test failure."""
    from autonomous.ai.exceptions import (
        GenerateJSONEmptyResponseError,
        MalformedResponseError,
    )
    from autonomous.ai.models import openai_compat

    # Reset the per-process strict-unsupported cache so the strict probe
    # actually fires for this test's (model, endpoint) pair.
    openai_compat._UNSUPPORTED_STRICT_MODE.discard(
        (client._json_model, client._base_url)
    )

    # First call: strict-mode request. Build a 400 response whose body
    # text contains a strict-mode marker ("response_format") so
    # _looks_like_unsupported_strict_mode → True and the fallback fires.
    # _resp() defaults status_code=200; override on the MagicMock directly.
    strict_resp = MagicMock()
    strict_resp.status_code = 400
    strict_resp.text = "error: unsupported response_format parameter"

    # Second call: loose-mode retry. Return a malformed-200 body so
    # _chat raises MalformedResponseError, which the fallback except
    # block catches and re-translates to GenerateJSONEmptyResponseError.
    loose_resp = _resp(json_data={"choices": []}, text='{}')

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Source's _chat: `body = response.json()` then `body[...]`.
            # The strict path needs `response.json()` to succeed enough
            # to reach `raise_for_status()` — but `_post` returns the
            # response BEFORE the source's `_chat` runs `.json()`.
            # Actually _post is what calls raise_for_status (via
            # HttpClient.request). Since we're patching _HTTP.post
            # directly, we have to raise HTTPError ourselves to simulate
            # what raise_for_status would have done.
            raise requests.HTTPError("400 Bad Request", response=strict_resp)
        return loose_resp

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        side_effect=fake_post,
    ):
        with pytest.raises(GenerateJSONEmptyResponseError) as excinfo:
            client.generate_json(
                "describe a thing",
                json_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            )

    msg = str(excinfo.value)
    assert "after fallback retry" in msg, (
        f"the fallback-path translation must produce the 'after fallback "
        f"retry' diagnostic envelope so operators can distinguish from "
        f"the strict-path translation; got {msg!r}"
    )
    assert isinstance(excinfo.value.__cause__, MalformedResponseError), (
        f"fallback path must chain MalformedResponseError → "
        f"GenerateJSONEmptyResponseError via `from inner_exc`; got "
        f"__cause__={excinfo.value.__cause__!r}"
    )
    # The strict-unsupported endpoint should now be cached so a future
    # call goes straight to loose mode.
    assert (client._json_model, client._base_url) in openai_compat._UNSUPPORTED_STRICT_MODE


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


def test_get_embedding_error_carries_body_excerpt_as_attribute(client):
    """Post-#83 body_excerpt lives on the exception attribute, not in
    the message string. Same operator-triage intent (see whatever came
    back without re-running the call) just via the structured carrier.
    Source-and-test inseparable under the #50 migration pattern."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={"data": []}, text="embeddings backend OOM"),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.get_embedding("anything")
    exc = excinfo.value
    assert exc.body_excerpt == "embeddings backend OOM"
    assert exc.endpoint == "/embeddings"
    assert exc.status == 200


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
