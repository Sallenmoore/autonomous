"""Canonical AI-adapter contract — slice 1 of #47.

Pins the method signatures every adapter in
``BaseAgent.MODEL_REGISTRY`` is expected to expose, plus the typed
``NotSupportedByProvider`` exception that supersedes raw
``NotImplementedError`` (issue #47 step 2).

Originally shipped with the conformance test
(``tests/unit/test_unit_ai_protocol_conformance.py``) carrying
``_KNOWN_DRIFT`` xfails for every adapter that hadn't yet been
migrated to match. Each later slice fixed adapters and removed the
corresponding xfail; ``_KNOWN_DRIFT`` was emptied at slice 3 and the
conformance test now passes outright with no xfails. The catalog
remains in place as the forcing function for any FUTURE adapter or
method addition.

Design choices:

- ``Protocol`` (structural typing), not ``ABC`` (nominal). Adapters
  inherit from ``AutoModel``; forcing a second inheritance just to
  enforce this contract would ripple through the descriptor layer.
  Protocols verify by structure — the conformance test does the
  runtime checking.
- Parameters declared as positional-or-keyword (no ``*,``). The
  existing dispatch layer (``jsonagent.py``) and tests pass kwargs by
  name, so kwarg-only would be a no-op change at call sites; matching
  the existing adapter shape keeps the conformance test focused on
  drift rather than on a cosmetic style flip.
- ``NotSupportedByProvider`` extends ``NotImplementedError`` so
  existing ``except NotImplementedError`` catches keep working
  through the migration. The typed exception carries ``method`` and
  ``provider`` attributes so dispatch layers can introspect (e.g.
  ``ImageAgent`` falling back to another provider on the same call).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class NotSupportedByProvider(NotImplementedError):
    """An adapter declared a method but does not implement it for this
    (provider, method) combination.

    Supersedes raw ``NotImplementedError`` at adapter boundaries
    (issue #47 step 2). Carries enough structured context that
    dispatch layers can introspect — e.g. ``ImageAgent`` can route to
    a different provider on the same call instead of leaking the
    exception to the caller.

    Subclasses ``NotImplementedError`` so existing
    ``except NotImplementedError`` callers remain correct during the
    multi-slice migration; new callers should catch
    ``NotSupportedByProvider`` specifically.
    """

    def __init__(self, method: str, provider: str, message: str | None = None):
        self.method = method
        self.provider = provider
        super().__init__(
            message or f"{provider!r} does not implement {method}()"
        )


@runtime_checkable
class AIModelProtocol(Protocol):
    """The canonical adapter contract for every entry in
    ``BaseAgent.MODEL_REGISTRY``.

    Conformance is verified by
    ``tests/unit/test_unit_ai_protocol_conformance.py``. Known current
    drift is enumerated there as ``xfail`` entries tagged with the
    slice that will fix each one; passing xfails are the progress
    signal for the rest of #47.

    Return-shape pins (the conformance test cannot enforce these via
    signature inspection — slice 4 adds runtime instance tests):
    - ``generate_json`` → ``dict``
    - ``generate_transcription`` → ``dict`` with keys ``{"text", "segments"}``
    - ``generate_image`` → ``bytes``
    - ``upscale_image`` → ``bytes``

    Kwarg-naming convention worth pinning explicitly because the
    issue called it out:
    - ``generate_image`` takes ``files=`` (plural — the optional
      img2img source-image list).
    - ``upscale_image`` takes ``image_content=`` (singular — the one
      image being upscaled).
    These are semantically different inputs, so they stay distinct.
    """

    def generate_json(
        self,
        message: str,
        system_prompt: str | None = None,
        json_schema: dict | None = None,
        schema_name: str = "response",
        uri: str = "",
        context: dict | None = None,
        temperature: float | None = None,
    ) -> dict: ...

    def generate_transcription(
        self,
        audio_file: Any,
        prompt: str = "",
    ) -> dict: ...

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        files: Any = None,
        aspect_ratio: str = "2KPortrait",
        style: Any = None,
    ) -> bytes: ...

    def upscale_image(
        self,
        prompt: str,
        image_content: bytes | None = None,
        aspect_ratio: str = "2KPortrait",
        style: Any = None,
    ) -> bytes: ...


__all__ = ["AIModelProtocol", "NotSupportedByProvider"]
