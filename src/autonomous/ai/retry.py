"""Tiny retry helper used by the AI model adapters.

Centralizes the retry / backoff / on-retry-callback pattern that was
duplicated across ``LocalAIModel.generate_json`` and ``generate_text``.
Pure stdlib; tests are in ``tests/unit/test_unit_retry.py``.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Callable

#: A pluggable hook called between attempts. ``attempt`` is 1-indexed
#: (the attempt that just failed); ``exc`` is the raised exception.
RetryHook = Callable[[int, BaseException], None]

# Sentinel that distinguishes "default not supplied" (re-raise on
# exhaustion) from "default explicitly set to None" (return None).
_NO_DEFAULT: Any = object()


def retry(
    func: Callable[[], Any],
    *,
    max_attempts: int = 3,
    sleep_seconds: float = 0,
    backoff_factor: float = 1.0,
    jitter: float = 0.0,
    catch: tuple[type[BaseException], ...] = (Exception,),
    on_retry: RetryHook | None = None,
    default: Any = _NO_DEFAULT,
) -> Any:
    """Run ``func()`` up to ``max_attempts`` times with simple backoff.

    Returns the successful result. If every attempt raises a ``catch``
    exception, the final exception propagates — unless ``default`` is
    explicitly provided, in which case it's returned instead (matches
    the legacy "log and return empty" behavior of the AI adapters).

    Between failed attempts:

    1. ``on_retry(attempt_number, exc)`` is invoked if supplied. The
       attempt number is 1-indexed and refers to the attempt that just
       failed. Useful for "flush model memory before retry" logic.
    2. ``time.sleep`` runs if ``sleep_seconds`` is positive. The base
       sleep grows geometrically with ``backoff_factor``: the wait
       BEFORE attempt ``n`` (1-indexed) is
       ``sleep_seconds * backoff_factor ** (n - 1)``. With the default
       ``backoff_factor=1.0`` this is the legacy flat backoff — every
       gap is exactly ``sleep_seconds`` — so existing callers are
       unaffected. ``backoff_factor=2.0`` yields ``sleep_seconds``,
       ``2*sleep_seconds``, ``4*sleep_seconds``, … (classic exponential
       backoff that rides out longer degraded windows without inflating
       the fast-path attempt count). If ``jitter`` is also positive, the
       geometric base is then scaled by
       ``uniform(1 - jitter, 1 + jitter)`` — randomizes the sleep
       duration so many concurrent retriers don't wake in lockstep and
       re-flood a recovering service.

    The hook never sleeps after the *final* attempt — there's nothing
    left to retry.

    Args:
        backoff_factor: Geometric growth base for the inter-attempt
            sleep. ``1.0`` (default) keeps the legacy flat backoff —
            existing callers are unaffected. Must be ``>= 1.0``; values
            below 1.0 (shrinking backoff) are rejected as almost always
            a config error, and a non-finite value (NaN/±Inf) would
            otherwise propagate into ``time.sleep`` and explode mid-loop
            (same defect class the ``jitter`` guard below covers).
        jitter: Fraction in ``[0, 1)``. ``0.0`` (default) disables
            jitter — existing callers are unaffected. ``0.3`` means the
            actual sleep is between 70% and 130% of the (possibly
            backed-off) base.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    # NaN comparison semantics: `NaN < 0` and `NaN >= 1` are both
    # False, so a bare `<` / `>=` check accepts NaN — which then
    # propagates to `random.uniform` and `time.sleep` and explodes
    # partway through a retry loop with no breadcrumb. ``math.isfinite``
    # rejects NaN AND ±Infinity (+Inf would fail the `>= 1` check
    # but NaN slipped through). See issue #77.
    if not math.isfinite(jitter) or jitter < 0 or jitter >= 1:
        raise ValueError("jitter must be a finite float in [0, 1)")
    # Same NaN/±Inf rationale as the jitter guard above: a non-finite
    # ``backoff_factor`` would survive a bare ``< 1.0`` check (``NaN <
    # 1.0`` is False) and then poison ``backoff_factor ** (attempt - 1)``
    # → ``time.sleep`` mid-loop. ``< 1.0`` also rejects shrinking
    # backoff, which is almost always a config typo (a caller wanting
    # "no backoff" passes the default 1.0, not 0.5). See issue #182.
    if not math.isfinite(backoff_factor) or backoff_factor < 1.0:
        raise ValueError("backoff_factor must be a finite float >= 1.0")

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except catch as exc:
            last_exc = exc
            if attempt < max_attempts:
                if on_retry is not None:
                    on_retry(attempt, exc)
                if sleep_seconds > 0:
                    # ``attempt`` is 1-indexed, so the first inter-attempt
                    # gap (after attempt 1) uses ``backoff_factor ** 0 ==
                    # 1`` — i.e. plain ``sleep_seconds`` — and each
                    # subsequent gap multiplies by ``backoff_factor``.
                    # With the default 1.0 this is the legacy flat sleep.
                    actual_sleep = sleep_seconds * backoff_factor ** (attempt - 1)
                    if jitter > 0:
                        actual_sleep *= random.uniform(1 - jitter, 1 + jitter)
                    time.sleep(actual_sleep)

    if default is _NO_DEFAULT:
        assert last_exc is not None
        raise last_exc
    return default
