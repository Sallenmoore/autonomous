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
