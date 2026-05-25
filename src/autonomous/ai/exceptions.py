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

    The first ~500 chars of the unparseable text are kept on ``.raw``
    for diagnostics — caller code can log it without re-fetching.
    """

    def __init__(self, msg: str, raw: str = "") -> None:
        super().__init__(msg)
        self.raw = raw
