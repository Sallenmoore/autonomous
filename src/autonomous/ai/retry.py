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
    2. ``time.sleep`` runs if ``sleep_seconds`` is positive. If
       ``jitter`` is also positive, the actual sleep is
       ``sleep_seconds * uniform(1 - jitter, 1 + jitter)`` — randomizes
       the sleep duration so many concurrent retriers don't wake in
       lockstep and re-flood a recovering service.

    The hook never sleeps after the *final* attempt — there's nothing
    left to retry.

    Args:
        jitter: Fraction in ``[0, 1)``. ``0.0`` (default) disables
            jitter — existing callers are unaffected. ``0.3`` means the
            actual sleep is between 70% and 130% of ``sleep_seconds``.
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
                    actual_sleep = sleep_seconds
                    if jitter > 0:
                        actual_sleep *= random.uniform(1 - jitter, 1 + jitter)
                    time.sleep(actual_sleep)

    if default is _NO_DEFAULT:
        assert last_exc is not None
        raise last_exc
    return default
