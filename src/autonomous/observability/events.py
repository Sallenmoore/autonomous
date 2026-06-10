"""Structured event helper — bridges field-based emission to the
legacy ``autonomous.log()`` singleton.

Emission sites today write either:

- ``log(f"[HPC-UNREACHABLE] signature={s} ...", _print=True)`` —
  free-form prefix + string interpolation; consumers grep the prefix.
- ``print("[HPC-UNREACHABLE] ...")`` — bypasses ``log()`` entirely
  (``db_sync._emit_hpc_unreachable``).
- ``log(f"Image route: requested={r} effective={e} ratio={a}")`` —
  field-shaped content stuffed into a single string.

``event(name, **fields)`` lets emission sites write:

    event("hpc_unreachable", provider="openai", status=500,
          signature="openai:HPCUnreachableError")

The helper:

1. Formats a human-readable line containing the legacy sentinel
   prefix (when supplied via ``marker=``) plus the field dict, so
   existing grep workflows ("look for ``[HPC-UNREACHABLE]``") keep
   working unchanged.
2. Returns the event dict so callers can attach it to RQ job meta,
   API response bodies, or future structured-log handlers.

This slice does NOT replace ``log()``. A follow-up slice swaps the
``log()`` singleton for stdlib ``logging`` with a JSON formatter —
when that lands, ``event()`` will emit structured records directly
and skip the string-formatting step. Today, ``event()`` is a forward-
compatible call shape that adapters can adopt now without waiting.
"""

from __future__ import annotations

from typing import Any

# Levels mirror stdlib logging names (case-insensitive). Kept loose
# for the slice-1 shim so adapters can use "info" / "warning" without
# importing logging constants. The follow-up slice will map these to
# real logging.LEVELS.
_VALID_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


def format_event(
    name: str,
    *,
    marker: str | None = None,
    **fields: Any,
) -> str:
    """Render an event as a single human-readable line.

    Format (designed to be both grep-friendly and structured-parser
    -friendly):

        [MARKER] event=<name> key1=value1 key2=value2

    The ``[MARKER]`` prefix is omitted when ``marker`` is None — used
    by events that don't need a legacy sentinel (new emission sites).
    Field values are repr-ed when they contain spaces / special chars
    so the line stays parseable; plain values pass through.

    Public helper because tests + a future stdlib-logging migration
    both want to format without emitting.
    """
    parts: list[str] = []
    if marker:
        parts.append(f"[{marker}]")
    parts.append(f"event={name}")
    for key, value in fields.items():
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _format_value(value: Any) -> str:
    """Render a single field value. Strings / numbers / bools pass
    through bare; everything else (dict, list, exception) is repr'd
    so the line stays single-line."""
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    if isinstance(value, str):
        # Quote only when the string would otherwise break the
        # ``key=value`` parser shape — embedded spaces / equals.
        if any(c in value for c in (" ", "=", "\t", "\n")):
            return repr(value)
        return value
    return repr(value)


def event(
    name: str,
    *,
    level: str = "info",
    marker: str | None = None,
    print_to_stdout: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    """Emit a structured event and return its field dict.

    Args:
        name: Stable event identifier (e.g. ``"hpc_unreachable"``,
            ``"structured_outputs_unavailable"``,
            ``"image_route_resolved"``). Convention: snake_case, no
            module prefix.
        level: Severity (``"debug"`` / ``"info"`` / ``"warning"`` /
            ``"error"`` / ``"critical"``). Honored when the follow-up
            slice migrates ``log()`` to stdlib logging; in this slice
            it's a tag in the returned dict for forward-compat.
        marker: Optional legacy-sentinel prefix (``"HPC-UNREACHABLE"``,
            ``"STRUCTURED-OUTPUTS-UNAVAILABLE"``). Renders as
            ``[MARKER]`` at the start of the formatted line so
            existing grep workflows keep matching.
        print_to_stdout: Mirror to stdout via ``log(..., _print=True)``.
            Off by default; turn on for operator-actionable events.
        **fields: Structured fields attached to the event.

    Returns:
        The event dict ``{"event": name, "level": level, **fields}``.
        Callers attach this to RQ ``job.meta``, API responses, or
        wherever structured payloads need to travel.
    """
    level_lower = level.lower()
    if level_lower not in _VALID_LEVELS:
        raise ValueError(
            f"event() level must be one of {sorted(_VALID_LEVELS)}, got {level!r}"
        )

    line = format_event(name, marker=marker, **fields)

    # Defer the ``autonomous.log`` import to call time. Importing
    # ``autonomous`` at module load runs ``load_dotenv()`` and pulls
    # the package ``__init__.py`` chain; tests that monkey-patch the
    # logger want a fresh resolve per call, and we want to avoid a
    # circular import if observability ever moves up the dep graph.
    from autonomous import log

    log(line, _print=print_to_stdout)

    payload: dict[str, Any] = {"event": name, "level": level_lower}
    if marker:
        payload["marker"] = marker
    payload.update(fields)
    return payload
