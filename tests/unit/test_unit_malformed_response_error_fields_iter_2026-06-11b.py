"""Independent committed coverage for PR #95 / issues #82 + #83.

PR #95 restructures ``MalformedResponseError`` to carry diagnostic state
as instance attributes (``endpoint``, ``status``, ``body_excerpt``)
instead of baking everything into the formatted message string. The
200-char excerpt bound moves into the constructor as ``_EXCERPT_MAX``
so a future raise site can't pick a different bound. Additive change:
``MalformedResponseError("msg")`` still works for legacy callers.

PR #95 also closes the #76 "Known gap" by adding malformed-2xx
translation to ``OpenAIClient.generate_transcription`` (issue #82) —
mirrors the ``_chat`` / ``get_embedding`` translation pattern, populates
the new structured fields with ``endpoint="/audio/transcriptions"``,
``status=response.status_code``, ``body_excerpt=response.text``.

Independent perspective (no peek at dev's ``tests/_dev_local/``):
- Constructor pin: kwargs exist with documented defaults; bare-msg call
  still constructs (additive).
- ``_EXCERPT_MAX`` is exactly 200 and lives on the class (not per-site).
- ``body_excerpt`` truncation enforced in constructor (length bound holds
  regardless of input length).
- bytes/bytearray ``body_excerpt`` is decoded with utf-8 + replace
  (operator-safe — no UnicodeDecodeError raised IN the error path).
- ``generate_transcription`` happy path returns the expected
  ``{"text", "segments"}`` shape (regression guard).
- ``generate_transcription`` translates non-JSON 2xx (ValueError on
  ``.json()``) and non-dict 2xx (AttributeError on ``.get()``) to
  ``MalformedResponseError`` with the new structured fields populated.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# #83 — MalformedResponseError structured fields
# ---------------------------------------------------------------------------


def test_excerpt_max_is_200_and_lives_on_the_class():
    """Bound lives on the class as a documented constant, not as a magic
    number sprinkled across raise sites. A future raise site reads
    ``MalformedResponseError._EXCERPT_MAX`` instead of guessing 200."""
    from autonomous.ai.exceptions import MalformedResponseError

    assert MalformedResponseError._EXCERPT_MAX == 200, (
        f"_EXCERPT_MAX must be 200 (the documented bound); "
        f"got {MalformedResponseError._EXCERPT_MAX!r}"
    )


def test_bare_message_call_still_works_additive_change():
    """Pre-#83 callers did ``raise MalformedResponseError("msg")``. The
    additive constructor must keep this working with all-default fields."""
    from autonomous.ai.exceptions import MalformedResponseError

    exc = MalformedResponseError("bare msg")
    assert str(exc) == "bare msg"
    assert exc.endpoint == "", f"endpoint default must be empty str; got {exc.endpoint!r}"
    assert exc.status is None, f"status default must be None; got {exc.status!r}"
    assert exc.body_excerpt == "", f"body_excerpt default must be empty str; got {exc.body_excerpt!r}"


def test_structured_fields_are_accessible_when_populated():
    """Pin the constructor signature: ``endpoint``, ``status``,
    ``body_excerpt`` are keyword-only and accessible on the instance."""
    from autonomous.ai.exceptions import MalformedResponseError

    exc = MalformedResponseError(
        "shape failure",
        endpoint="/chat/completions",
        status=200,
        body_excerpt="actual body content here",
    )
    assert exc.endpoint == "/chat/completions"
    assert exc.status == 200
    assert exc.body_excerpt == "actual body content here"
    # Message is still distinct from body_excerpt — pre-#83 the excerpt
    # was baked into the message; post-#83 it lives on a separate field.
    assert "actual body content" not in str(exc), (
        f"post-#83 the body_excerpt must live on the instance, NOT be "
        f"baked into str(exc); got {str(exc)!r}"
    )


def test_body_excerpt_truncated_in_constructor_regardless_of_input_length():
    """The bound is enforced in ``__init__``, not at the raise site.
    Pass a 5000-char body; the stored value must be exactly 200 chars.
    A regression that moved truncation back to the raise site would
    silently re-introduce per-site drift."""
    from autonomous.ai.exceptions import MalformedResponseError

    huge = "X" * 5000
    exc = MalformedResponseError("test", body_excerpt=huge)
    assert len(exc.body_excerpt) == 200, (
        f"constructor must truncate to _EXCERPT_MAX=200; got "
        f"len={len(exc.body_excerpt)}"
    )
    assert exc.body_excerpt == "X" * 200


def test_body_excerpt_bytes_decoded_with_replace_errors():
    """Defensive bytes-to-str coercion. A caller mistake (passing
    ``response.content`` instead of ``.text``) should NOT silently
    leave bytes on a documented-str field. UTF-8 decode with
    ``errors="replace"`` matches ``requests.Response.text``'s tolerance
    — better a U+FFFD in the excerpt than a UnicodeDecodeError raised
    IN the error-handling path."""
    from autonomous.ai.exceptions import MalformedResponseError

    raw_bytes = b"valid-ascii\xff\xfeand-invalid"
    exc = MalformedResponseError("test", body_excerpt=raw_bytes)
    assert isinstance(exc.body_excerpt, str), (
        f"body_excerpt must be str even when bytes was passed; got "
        f"type={type(exc.body_excerpt).__name__}"
    )
    # The invalid bytes \xff\xfe should be replaced with U+FFFD chars,
    # not raise UnicodeDecodeError.
    assert "valid-ascii" in exc.body_excerpt
    assert "and-invalid" in exc.body_excerpt


def test_body_excerpt_bytearray_also_decoded():
    """Sibling defensive coercion: bytearray is structurally distinct
    from bytes but the same caller-mistake risk applies."""
    from autonomous.ai.exceptions import MalformedResponseError

    raw = bytearray(b"some content")
    exc = MalformedResponseError("test", body_excerpt=raw)
    assert isinstance(exc.body_excerpt, str)
    assert exc.body_excerpt == "some content"


def test_status_accepts_int_and_none():
    """Pin the type contract: ``int | None``. None when caller doesn't
    know the status; int otherwise."""
    from autonomous.ai.exceptions import MalformedResponseError

    a = MalformedResponseError("a", status=200)
    b = MalformedResponseError("b", status=None)
    assert a.status == 200
    assert b.status is None


# ---------------------------------------------------------------------------
# #82 — generate_transcription malformed-2xx translation
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


def _resp(json_data=None, *, text='{}', status=200, json_raises=None):
    r = MagicMock()
    r.status_code = status
    if json_raises is not None:
        r.json.side_effect = json_raises
    else:
        r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status.return_value = None
    return r


def test_transcription_happy_path_returns_text_and_segments_dict(client):
    """Regression guard — the malformed-2xx translation must not break
    the happy-path extraction. Pin the documented shape."""
    body = {"text": "hello world", "segments": [{"id": 0, "text": "hello"}]}
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data=body, text='{"text": "hello world", ...}'),
    ):
        result = client.generate_transcription(b"audio-bytes")

    assert result == {
        "text": "hello world",
        "segments": [{"id": 0, "text": "hello"}],
    }


def test_transcription_happy_path_defaults_when_keys_missing(client):
    """Server returned a 200 with empty body — ``body.get(...)`` defaults
    apply. Must NOT raise MalformedResponseError on this path."""
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(json_data={}, text="{}"),
    ):
        result = client.generate_transcription(b"audio")
    assert result == {"text": "", "segments": []}


def test_transcription_raises_malformed_on_non_json_body(client):
    """Non-JSON 2xx body — ``response.json()`` raises ``ValueError``
    (via json.JSONDecodeError). Must translate to MalformedResponseError
    (issue #82, same family as #76)."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            text="<html>504 bad gateway</html>",
            json_raises=ValueError("Expecting value: line 1 column 1 (char 0)"),
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_transcription(b"audio")

    exc = excinfo.value
    assert exc.endpoint == "/audio/transcriptions", (
        f"endpoint field must identify the transcription path for "
        f"observability triage; got {exc.endpoint!r}"
    )


def test_transcription_raises_malformed_on_non_dict_body(client):
    """When the 2xx body is a list (or None) rather than a dict,
    ``body.get(...)`` raises ``AttributeError`` — must translate. This
    is the case the #76 ship explicitly left as a "known gap" and #82
    closes."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data=["unexpected", "list", "shape"],
            text='["unexpected", "list", "shape"]',
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_transcription(b"audio")

    assert excinfo.value.endpoint == "/audio/transcriptions"


def test_transcription_malformed_response_carries_structured_fields(client):
    """Pin the end-to-end #82 + #83 integration: the
    MalformedResponseError raised from generate_transcription must
    populate all three structured fields (endpoint, status,
    body_excerpt) using the new constructor — not bake them into the
    message string."""
    from autonomous.ai.exceptions import MalformedResponseError

    body_text = "unexpected server output that operators will want to see"
    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data=None,
            text=body_text,
            json_raises=ValueError("not json"),
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_transcription(b"audio")

    exc = excinfo.value
    assert exc.endpoint == "/audio/transcriptions"
    assert exc.status == 200
    assert "unexpected server output" in exc.body_excerpt, (
        f"body_excerpt must carry the actual server body content for "
        f"operator triage; got {exc.body_excerpt!r}"
    )


def test_transcription_malformed_response_cause_chain_preserved(client):
    """``from exc`` must be in place so consumers walking ``__cause__``
    can still find the stdlib origin (ValueError for json failure,
    AttributeError for non-dict). #82's translation must not break the
    chain that #76 already established for sibling methods."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data=None,
            text="not json",
            json_raises=ValueError("not json"),
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_transcription(b"audio")
    assert isinstance(excinfo.value.__cause__, ValueError), (
        f"cause chain must point to original ValueError; got "
        f"__cause__={excinfo.value.__cause__!r}"
    )


# ---------------------------------------------------------------------------
# Cross-method consistency — every malformed-2xx raise site uses the
# documented 5-tuple catch and populates all three new fields.
# ---------------------------------------------------------------------------


def test_chat_also_populates_structured_fields_after_83(client):
    """The #83 restructure also migrated _chat's existing translation
    to the new constructor. Verify it populates fields (catches a
    regression where _chat fell behind and kept baking excerpt into
    message)."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data={"choices": []},
            text='chat backend returned empty choices',
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.generate_text("anything")

    exc = excinfo.value
    assert exc.endpoint == "/chat/completions"
    assert exc.status == 200
    assert "chat backend" in exc.body_excerpt


def test_get_embedding_also_populates_structured_fields_after_83(client):
    """Same as the _chat coverage — pin get_embedding's migration."""
    from autonomous.ai.exceptions import MalformedResponseError

    with patch(
        "autonomous.ai.models.openai_compat._HTTP.post",
        return_value=_resp(
            json_data={"data": []},
            text='embeddings backend OOM',
        ),
    ):
        with pytest.raises(MalformedResponseError) as excinfo:
            client.get_embedding("anything")

    exc = excinfo.value
    assert exc.endpoint == "/embeddings"
    assert exc.status == 200
    assert "embeddings backend" in exc.body_excerpt
