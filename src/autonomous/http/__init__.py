"""Centralized HTTP-client primitive for adapter call sites.

The library historically grew one ``requests.Session`` + ad-hoc retry
loop per subsystem (``ai.models.openai_compat``, ``ai.models.local_model``,
``ai.models.gemini``, ``ai.models.flux``, ``db.db_sync``, ``auth.autoauth``).
Each call site reinvented timeout policy, retry semantics, transport-
failure classification, and observability sentinel emission — and missed
edges (timeouts on auth fetches, retry on local_model, 500 in openai's
transport-failure set until issue #39).

``HttpClient`` consolidates the shape:

- One ``requests.Session`` per client instance (connection pooling
  preserved per-adapter).
- Configurable timeout with per-call override.
- Optional retry via ``autonomous.ai.retry.retry`` for transport-class
  failures.
- Pluggable transport-failure classification (5xx range + opt-in 4xx
  codes like 401 for token-expired flows).
- Observability hooks (``on_request`` / ``on_response`` / ``on_failure``)
  that downstream adapters can wire to structured logging + metrics
  (the ``autonomous.observability`` module from issue #51's slice 1).

This is the **foundation slice** of issue #50. Existing adapters are
NOT migrated in this slice; they continue using their per-module
``requests.Session()`` until a follow-up slice retargets them one by
one. Importing this module has no side effects on those adapters.
"""

from autonomous.http.client import HttpClient, TransportError, is_transport_failure

__all__ = ["HttpClient", "TransportError", "is_transport_failure"]
