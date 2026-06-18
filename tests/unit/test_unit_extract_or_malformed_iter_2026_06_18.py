"""Independent second-perspective coverage for PR #156.

PR #156 (closes #142) extracts ``_extract_or_malformed`` from
``openai_compat`` into a shared module ``autonomous.ai._extract``
and adopts it at four call sites (``flux.generate_image``,
``local_model.generate_json`` / ``generate_text`` /
``generate_transcription``). Dev's committed test changes are
limited to renaming two ``test_unit_flux.py`` cases to expect
``MalformedResponseError`` — the new helper itself has **no direct
committed unit tests**, and the three adopted ``local_model`` sites
also have no committed coverage of their malformed-2xx contract.

This file fills both gaps:

1. **Direct helper unit tests** for
   ``autonomous.ai._extract.extract_or_malformed``: every member of
   ``MALFORMED_2XX_EXCEPTIONS`` translates to ``MalformedResponseError``;
   the ``endpoint`` label survives; ``body_excerpt`` reads from
   ``response.text``; ``__cause__`` chains the original exception;
   happy-path return values flow through unchanged; out-of-tuple
   exceptions propagate.

2. **Adoption-site tests for the three ``local_model`` methods** that
   dev's PR didn't add committed coverage for:
   - ``generate_json``: malformed body translates to
     ``GenerateJSONEmptyResponseError`` (the outer except chain at
     ``local_model.py:364-372``).
   - ``generate_text``: malformed body returns the
     ``"Error generating text."`` literal degrade contract.
   - ``generate_transcription``: malformed body returns
     ``{"segments": [], "text": ""}`` degrade contract.

Hermetic — stubs ``_HTTP`` and ``AutoTasks`` so no Ollama / Redis I/O.
"""

import pytest

from autonomous.ai import _extract
from autonomous.ai._extract import extract_or_malformed
from autonomous.ai.exceptions import (
    MALFORMED_2XX_EXCEPTIONS,
    GenerateJSONEmptyResponseError,
    MalformedResponseError,
)
from autonomous.ai.models import local_model
from autonomous.ai.models.local_model import LocalAIModel


# ---------------------------------------------------------------------------
# Independent stubs — rebuilt from scratch, not imported from dev's helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal requests.Response stand-in for the helper.

    ``payload`` is what ``.json()`` returns by default; when
    ``json_raises`` is set, ``.json()`` raises that exception instead.
    ``.text`` is the body excerpt source; ``.status_code`` is preserved
    so ``from_response`` can read it.
    """

    def __init__(
        self,
        payload=None,
        *,
        json_raises=None,
        text="raw body excerpt for diagnostics",
        status_code=200,
    ):
        self._payload = payload
        self._json_raises = json_raises
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def json(self):
        if self._json_raises is not None:
            raise self._json_raises
        return self._payload


def _local_instance():
    """Bare LocalAIModel stand-in. Mirrors the pattern in
    ``tests/unit/test_unit_local_model_outer_retry_no_httperror_iter_2026-06-11d.py``
    so the stub stays consistent with the rest of the LocalAIModel
    unit tier."""
    inst = LocalAIModel.__new__(LocalAIModel)
    object.__setattr__(inst, "_data", {"instructions": "x", "name": "t"})
    object.__setattr__(inst, "_dynamic_fields", {})
    object.__setattr__(inst, "_changed_fields", [])
    object.__setattr__(inst, "_initialised", True)
    object.__setattr__(inst, "_created", False)
    object.__setattr__(inst, "_retry_sleep", 0.0)
    object.__setattr__(inst, "_text_model", "m")
    object.__setattr__(inst, "_ollama_url", "http://stub:11434")
    object.__setattr__(inst, "_audio_url", "http://stub:8000")
    object.__setattr__(inst, "_context_limit", 1024)
    object.__setattr__(inst, "_json_timeout", 5)
    object.__setattr__(inst, "_text_timeout", 5)
    object.__setattr__(inst, "_media_timeout", 5)
    return inst


@pytest.fixture
def _no_autotasks(monkeypatch):
    """Stub AutoTasks so the rq/Redis path is never touched."""

    class _Stub:
        def get_current_task(self):
            return None

    monkeypatch.setattr(local_model, "AutoTasks", lambda: _Stub())


@pytest.fixture
def _no_flush(monkeypatch):
    """Stub flush_memory so the retry hook doesn't issue extra HTTP."""
    monkeypatch.setattr(
        LocalAIModel, "flush_memory", lambda self, model: None
    )


# ===========================================================================
# 1. Direct helper unit tests — the shared module has no other committed coverage
# ===========================================================================


class TestExtractOrMalformedTranslatesEveryCatchTupleMember:
    """Each member of ``MALFORMED_2XX_EXCEPTIONS`` becomes
    ``MalformedResponseError`` when raised inside the extractor."""

    @pytest.mark.parametrize(
        "raised",
        [
            AttributeError("dict.attr fail"),
            KeyError("missing-key"),
            IndexError("index out of range"),
            TypeError("wrong shape"),
            ValueError("malformed value"),
        ],
        ids=lambda e: type(e).__name__,
    )
    def test_extractor_exception_becomes_malformed(self, raised):
        # Sanity-check that the raised type is in the documented catch
        # tuple — surfaces a drift between this test's parametrize list
        # and ``MALFORMED_2XX_EXCEPTIONS`` if either is changed without
        # the other.
        assert isinstance(raised, MALFORMED_2XX_EXCEPTIONS)

        resp = _FakeResponse(payload={"shape": "valid-json"})

        def _extract(body):
            raise raised

        with pytest.raises(MalformedResponseError) as exc_info:
            extract_or_malformed(resp, "/test/endpoint", _extract)

        assert exc_info.value.__cause__ is raised
        assert exc_info.value.endpoint == "/test/endpoint"
        assert "/test/endpoint" in str(exc_info.value)
        # The original exception's message is interpolated into the
        # wrapper — pins the f-string at autoattr.py:43 against a
        # refactor that drops it.
        assert str(raised).split(":")[0] in str(exc_info.value) or str(
            raised
        ) in str(exc_info.value)


class TestExtractOrMalformedResponseJsonFailure:
    """``response.json()`` raising one of the catch-tuple exceptions
    (the JSONDecodeError → ValueError path) is also translated."""

    def test_json_decode_error_is_translated(self):
        # ``json.JSONDecodeError`` is a ``ValueError`` subclass, so
        # the catch tuple at ``_extract.py:40`` covers it. Pinning
        # the inheritance assumption: if a future stdlib release
        # changed the parent class, this test surfaces it.
        import json

        broken = json.JSONDecodeError("bad json", "doc", 0)
        assert isinstance(broken, ValueError)

        resp = _FakeResponse(json_raises=broken)

        def _extract(body):  # never reached — .json() raises first
            return body

        with pytest.raises(MalformedResponseError) as exc_info:
            extract_or_malformed(resp, "/json/parse", _extract)

        assert exc_info.value.__cause__ is broken


class TestExtractOrMalformedHappyPath:
    """No exception → the extractor's return value flows through
    unchanged. Pins that the helper doesn't accidentally wrap or
    transform the success path."""

    def test_extractor_return_value_is_forwarded(self):
        resp = _FakeResponse(payload={"choices": [{"text": "hello"}]})

        def _extract(body):
            return body["choices"][0]["text"]

        result = extract_or_malformed(resp, "/ok", _extract)
        assert result == "hello"

    def test_extractor_can_return_complex_object(self):
        # Pins that the helper is value-agnostic on the return —
        # dict / list / scalar all flow through.
        resp = _FakeResponse(payload=[1, 2, 3])
        result = extract_or_malformed(resp, "/ok", lambda b: b)
        assert result == [1, 2, 3]


class TestExtractOrMalformedDoesNotSwallowOutOfTuple:
    """Exceptions NOT in ``MALFORMED_2XX_EXCEPTIONS`` propagate verbatim.

    The bounded ``except`` is the whole point — a refactor that
    broadens to ``except Exception`` would silently absorb infra-class
    failures (``ConnectionError``, ``OSError``) as malformed bodies
    and lose the distinction that ``MalformedResponseError`` was
    invented for.
    """

    def test_runtime_error_propagates(self):
        resp = _FakeResponse(payload={"ok": True})

        def _extract(body):
            raise RuntimeError("infra failure during walk")

        with pytest.raises(RuntimeError, match="infra failure during walk"):
            extract_or_malformed(resp, "/infra", _extract)

    def test_os_error_propagates(self):
        # OSError is the catch-class shape for filesystem / socket-level
        # failures elsewhere in the project; it must NOT be absorbed as
        # malformed-2xx here.
        resp = _FakeResponse(payload={"ok": True})

        def _extract(body):
            raise OSError("socket gone")

        with pytest.raises(OSError, match="socket gone"):
            extract_or_malformed(resp, "/oserror", _extract)


class TestExtractOrMalformedEndpointLabelInterpolation:
    """The ``endpoint`` arg appears in both the constructed exception's
    ``.endpoint`` field AND in the message — pinning the dual surface
    so a refactor that drops one or the other gets caught."""

    def test_endpoint_in_message_and_attribute(self):
        resp = _FakeResponse(payload={})

        with pytest.raises(MalformedResponseError) as exc_info:
            extract_or_malformed(
                resp,
                "/api/chat-with-distinct-name",
                lambda b: b["nope"],  # KeyError
            )

        assert exc_info.value.endpoint == "/api/chat-with-distinct-name"
        assert "/api/chat-with-distinct-name" in str(exc_info.value)


# ===========================================================================
# 2. Adoption sites in local_model — three methods, no committed dev coverage
# ===========================================================================


class TestLocalModelGenerateJsonMalformedTranslation:
    """``LocalAIModel.generate_json`` outer-except chain catches
    ``MalformedResponseError`` and re-raises as
    ``GenerateJSONEmptyResponseError`` (local_model.py:364-372).

    Dev's PR description claimed this behavior but added no committed
    tests for it. Without coverage a refactor that drops the catch
    clause would silently leak the typed shape to callers."""

    def test_non_dict_body_translates_to_empty_response_error(
        self, monkeypatch, _no_autotasks, _no_flush
    ):
        # _HTTP.post returns a 2xx response whose .json() body is a
        # LIST instead of a dict. The extractor's ``body.get(...)``
        # call raises AttributeError → caught by extract_or_malformed
        # → translated to MalformedResponseError → caught by
        # generate_json's outer except → translated to
        # GenerateJSONEmptyResponseError.
        resp = _FakeResponse(payload=["choices", "are", "a", "list"])
        resp.raise_for_status = lambda: None

        monkeypatch.setattr(local_model._HTTP, "post", lambda *a, **k: resp)

        inst = _local_instance()

        with pytest.raises(GenerateJSONEmptyResponseError) as exc_info:
            inst.generate_json("any message")

        # The original MalformedResponseError survives on the __cause__
        # chain — pins the ``from exc`` at local_model.py:372 so an
        # observability layer that walks the chain can still see the
        # malformed-body fingerprint.
        assert isinstance(exc_info.value.__cause__, MalformedResponseError)


class TestLocalModelGenerateTextDegradeContract:
    """``LocalAIModel.generate_text`` returns the literal
    ``"Error generating text."`` on malformed-body — pins that the
    typed ``MalformedResponseError`` joins the existing degrade
    catch tuple at local_model.py:434-439 without changing the
    consumer-visible literal."""

    def test_non_dict_body_returns_error_literal(
        self, monkeypatch, _no_autotasks
    ):
        # Body is a scalar (a string) — not a dict. The extractor's
        # ``body.get("message", {})`` walk raises AttributeError →
        # extract_or_malformed translates → caught by the except
        # tuple in generate_text → degrade contract returns the
        # literal.
        resp = _FakeResponse(payload="raw text, not a dict")
        resp.raise_for_status = lambda: None

        monkeypatch.setattr(local_model._HTTP, "post", lambda *a, **k: resp)

        inst = _local_instance()
        result = inst.generate_text("any message")

        assert result == "Error generating text."


class TestLocalModelGenerateTranscriptionDegradeContract:
    """``LocalAIModel.generate_transcription`` returns the literal
    ``{"segments": [], "text": ""}`` on malformed-body. Pins the
    explicit ``_require_dict_body`` extractor at
    local_model.py:506-511 against a refactor that drops the
    isinstance check or changes the empty-dict shape."""

    def test_non_dict_body_returns_empty_transcript(
        self, monkeypatch, _no_autotasks
    ):
        # /transcribe returns a list body (e.g. a faulty server emits
        # the segments array as the top-level body). The
        # _require_dict_body extractor raises TypeError →
        # extract_or_malformed translates → caught in the except
        # tuple at local_model.py:516-521 → degrade contract.
        resp = _FakeResponse(payload=[{"start": 0, "end": 1}])
        resp.raise_for_status = lambda: None

        monkeypatch.setattr(local_model._HTTP, "post", lambda *a, **k: resp)

        inst = _local_instance()
        result = inst.generate_transcription(audio_file=b"fake-audio-bytes")

        assert result == {"segments": [], "text": ""}

    def test_dict_body_passes_through_unchanged(
        self, monkeypatch, _no_autotasks
    ):
        # Inverse: a well-formed dict body is returned VERBATIM. The
        # ``_require_dict_body`` extractor just returns ``body``
        # unchanged. Pins that the new extractor didn't accidentally
        # alter the happy-path response shape.
        expected = {"segments": [{"text": "hello"}], "text": "hello"}
        resp = _FakeResponse(payload=expected)
        resp.raise_for_status = lambda: None

        monkeypatch.setattr(local_model._HTTP, "post", lambda *a, **k: resp)

        inst = _local_instance()
        result = inst.generate_transcription(audio_file=b"fake-audio-bytes")

        assert result == expected


# ===========================================================================
# 3. The catch tuple itself — pin its contents
# ===========================================================================


class TestMalformed2xxExceptionsTupleContents:
    """Pins the exact membership of ``MALFORMED_2XX_EXCEPTIONS``.

    The constant is documented at ``exceptions.py:75-91`` as the
    single source of truth — drift between the constant and the
    docstring is what motivated #102. Pinning the membership means
    any add / remove forces a deliberate test update rather than
    silently widening or narrowing the catch.
    """

    def test_exact_membership(self):
        assert MALFORMED_2XX_EXCEPTIONS == (
            AttributeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        )

    def test_tuple_shape_not_list(self):
        # The catch syntax (``except (...,) as exc``) requires a
        # tuple, not a list. A refactor that switched to a list would
        # raise ``TypeError: catching classes that do not inherit from
        # BaseException is not allowed`` at every raise site. Cheap
        # pin against that mistake.
        assert isinstance(MALFORMED_2XX_EXCEPTIONS, tuple)
