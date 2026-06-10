"""Structured observability primitives — events + metrics.

Foundation slice for issue #51. Replaces the sentinel-string-prefix
contract (``[HPC-UNREACHABLE]``, ``[STRUCTURED-OUTPUTS-UNAVAILABLE]``,
``Image route: requested=...``) and the one-off ``record_embedding_
sync_event`` Redis counter with a structured field model + general
``Counter`` / ``Histogram`` primitives.

This slice ships the primitives only. Existing emission sites
(``db.db_sync``, ``ai.models.openai_compat``, etc.) continue to emit
the legacy sentinel strings via ``autonomous.log()``; per-subsystem
migration to ``observability.event(...)`` is a follow-up slice.

Public API:

- ``Counter`` / ``Histogram`` — process-wide metric primitives.
- ``counter(name, ...)`` / ``histogram(name, ...)`` — register-and-
  return helpers that use the default ``REGISTRY``.
- ``Registry`` — collection of metrics; ``REGISTRY`` is the process-
  default singleton (tests can construct fresh ones for isolation).
- ``event(name, *, level, **fields)`` — emit a structured event:
  formats the field dict for ``autonomous.log()`` AND returns the
  event dict so call sites can attach it to RQ job meta, JSON
  response bodies, etc.
"""

from autonomous.observability.events import event, format_event
from autonomous.observability.metrics import (
    REGISTRY,
    Counter,
    Histogram,
    Registry,
    counter,
    histogram,
)

__all__ = [
    "Counter",
    "Histogram",
    "Registry",
    "REGISTRY",
    "counter",
    "histogram",
    "event",
    "format_event",
]
