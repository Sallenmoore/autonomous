"""Typed exceptions for the AI model adapters.

Raised by ``generate_json`` on every real provider (``OpenAIClient``,
``LocalAIModel``, ``GeminiAIModel``) so consumers can distinguish failure
modes that warrant different retry / fallback policies. ``MockAIModel``
is intentionally exempt — it returns ``{}`` (or a context-stamped partial
dict) by design as the testing escape hatch.

The previous behavior was a silent ``return {}`` on parse / empty-body
failure, which collapsed three distinct failure modes into one
indistinguishable shape. See GH issue #124 and ``MIGRATIONS.md``.
"""

from __future__ import annotations


class GenerateJSONError(RuntimeError):
    """``generate_json`` could not produce a parseable JSON object.

    Base of the hierarchy — catch this if the caller treats all failure
    modes uniformly. Catch a subclass to branch on mode.
    """


class GenerateJSONEmptyResponseError(GenerateJSONError):
    """The endpoint returned an empty body / no choices / no candidates.

    Usually a transient transport hiccup (chat endpoint briefly returned
    a truncated 200, server overloaded, no completion produced). Retry
    is often viable; a prompt change is not the right response.
    """


class GenerateJSONParseError(GenerateJSONError):
    """The endpoint returned text that could not be parsed as JSON.

    Usually a deterministic model failure (returned prose, returned a
    JSON object that doesn't match the expected shape, etc.). Retrying
    with the same prompt usually won't help; a prompt change or a
    fallback path is the right response.

    The first ``_RAW_MAX`` chars of the unparseable text are kept on
    ``.raw`` for diagnostics — caller code can log it without re-fetching.
    Truncation lives in the constructor (not at each provider's call
    site) so a future provider can't forget the bound.

    When the failure is a *schema-validation* miss (the body parsed as
    JSON but didn't match the requested shape), the fully-parsed object
    is also attached, un-truncated, on ``.payload``. ``.raw`` stays the
    bounded human-diagnostic string; ``.payload`` is the programmatic
    recovery surface, letting a consumer normalize drifted keys / fill
    defaults / re-validate on the object already in hand instead of
    re-calling the model. It is ``None`` for every other failure mode:
    unparseable text, empty body, non-dict result (the model returned
    a list / scalar where an object was expected), AND the deliberate
    edge case where the *caller's schema* itself is structurally
    invalid (``jsonschema.SchemaError``). In the SchemaError case a
    parsed object DOES exist but ``.payload`` stays ``None`` because
    the model output is not the recovery surface — the caller's
    schema is the problem, not the response.

    ``.payload`` is the *live* parsed object, not a copy — a recovery
    routine that mutates it in place mutates the only artifact of the
    failed call. Deep-copy first if a pristine snapshot is needed.
    """

    _RAW_MAX = 500

    def __init__(self, msg: str, *, raw: str = "", payload=None) -> None:
        super().__init__(msg)
        self.raw = (raw or "")[: self._RAW_MAX]
        self.payload = payload


class MalformedResponseError(RuntimeError):
    """The endpoint returned a 2xx but the body shape was unextractable.

    Distinct from transport-class failures (e.g. ``HPCUnreachableError``):
    the request reached the endpoint and got back a 2xx; the body just
    didn't carry the fields the adapter needs. Distinct from
    ``GenerateJSONParseError``: the body may not even parse as JSON, or
    parses but lacks the expected keys/indices entirely (which is a
    response-shape failure, not a schema-validation failure).

    Raised by ``OpenAIClient._chat`` when ``response.json()`` raises
    ``json.JSONDecodeError`` or the ``choices[0].message.content`` walk
    raises ``KeyError`` / ``IndexError`` / ``TypeError``, and by
    ``OpenAIClient.get_embedding`` when ``data[0].embedding`` extraction
    fails the same way. Callers that previously caught a stdlib
    ``KeyError`` / ``IndexError`` from these methods should catch this
    instead — the prior behavior was a leaked stdlib exception that
    masked the distinction between transport-class and malformed-body
    failure modes (issue #76).
    """


class GeminiFileUploadTimeoutError(RuntimeError):
    """``GeminiAIModel._add_files`` polled past the upload-processing cap.

    Gemini's ``files.upload`` returns immediately with the file in state
    ``PROCESSING``; the caller polls ``get_file`` until the state flips
    to ``ACTIVE`` (or a terminal-failure state). The pre-#50 loop was
    unbounded, so a file genuinely stuck in PROCESSING (network drop
    mid-upload, malformed content the server can't decode, transient
    backend outage) would spin the worker forever with a half-second
    sleep between checks.

    Raised on cap exhaustion in lieu of returning a partial uploaded-files
    list — upload failure has no useful "partial," the caller assumes the
    list it gets back is fully processed. Consumers (e.g. storyteller)
    can catch this specific class to distinguish upload-stuck from other
    Gemini failure modes without parsing the message.

    Cap is wall-clock (``time.monotonic``), default 300s, override via
    ``GEMINI_UPLOAD_POLL_TIMEOUT`` env var. README #6.
    """
