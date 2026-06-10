"""``HttpClient`` — wraps ``requests.Session`` with consolidated retry,
timeout, transport-failure classification, and observability hooks.

Foundation slice for issue #50. Adapters migrate in follow-up slices;
this module ships without touching ``ai.models.*``, ``auth.autoauth``,
or ``db.db_sync``.

Design choices worth pinning:

- **Stateless across requests.** Headers/auth/cookies are passed per
  call, not stored on the client. Matches how the existing adapters
  use ``_SESSION`` (per-request ``headers=`` kwarg only), avoiding the
  classic "session.headers got mutated by a sibling thread" failure
  mode.
- **Retry delegates to ``autonomous.ai.retry.retry``.** Don't grow a
  second backoff helper; the existing one is battle-tested across the
  AI adapters and supports the ``on_retry`` + jitter hooks we need.
- **Transport-failure classification is configurable per client**, not
  global. ``openai_compat`` includes 401 (revoked token == same
  recovery path as VPN drop in the HPC deployment); ``local_model``
  does not (no auth). Per-instance config keeps that asymmetry honest.
- **Observability hooks are noop-by-default.** Adapters that don't
  migrate observability yet still get the retry/timeout benefits.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

import requests

from autonomous.ai.retry import retry


class TransportError(RuntimeError):
    """Raised when ``HttpClient`` classifies a response or exception as
    transport-class (retry-eligible).

    Adapters that already define their own typed exception
    (``HPCUnreachableError``, etc.) can wrap or re-raise from this; or
    they can pass ``transport_error_cls=`` to ``HttpClient`` so it
    raises their type directly. The default name is generic so the
    base library doesn't leak HPC-specific vocabulary.
    """


# Status codes >= 500 are always transport-class. Callers add extras
# (e.g. ``{401}`` for token-expired, ``{408, 429}`` for throttling) via
# ``HttpClient(transport_failure_codes=...)``.
RequestHook = Callable[[str, str, Mapping[str, str] | None, Any], None]
ResponseHook = Callable[[str, str, requests.Response, int], None]
FailureHook = Callable[[str, str, BaseException, int], None]


def is_transport_failure(
    status: Any,
    *,
    extra_codes: Iterable[int] = (),
) -> bool:
    """Predicate used by ``HttpClient`` for response-status routing.

    True iff ``status`` is in ``extra_codes`` OR is a numeric value
    ``>= 500``. The non-int branch (``MagicMock``, ``None``) returns
    False so test fixtures and surprise inputs degrade to "not
    transport-class" rather than crashing — same defensive shape as
    ``ai.models.openai_compat._is_transport_failure``.
    """
    extras = frozenset(extra_codes)
    if status in extras:
        return True
    try:
        return status >= 500
    except TypeError:
        return False


# Config / programmer-error exception types that should NOT be wrapped
# in ``TransportError`` — retrying against an invalid URL or missing
# schema burns attempts against an unfixable cause. Modeled after the
# exclusion tuple in ``ai.models.openai_compat._post``; SSLError and
# ProxyError are intentionally NOT here — both subclass ConnectionError
# and represent transient transport hiccups (renegotiation, intermittent
# proxy blips) that the retry loop should handle.
_NON_TRANSPORT_REQUESTS_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.exceptions.MissingSchema,
    requests.exceptions.InvalidURL,
    requests.exceptions.InvalidSchema,
    requests.exceptions.InvalidJSONError,
    requests.exceptions.URLRequired,
    requests.exceptions.InvalidHeader,
    requests.exceptions.InvalidProxyURL,
)


def _noop_request(method, url, headers, body):  # pragma: no cover - trivial
    return None


def _noop_response(method, url, response, attempt):  # pragma: no cover - trivial
    return None


def _noop_failure(method, url, exc, attempt):  # pragma: no cover - trivial
    return None


def _safe_hook(hook: Callable[..., None], *args: Any) -> None:
    """Invoke a user-supplied observability hook, swallowing + logging
    any exception it raises.

    The hooks are noop-by-default, so the caller never asked for
    observability to be load-bearing. A bug in an adapter's hook should
    not replace the in-flight ``TransportError`` / ``HTTPError`` with
    a hook-side ``KeyError`` — that loses the original failure cause.
    """
    try:
        hook(*args)
    except Exception as hook_exc:  # noqa: BLE001 — last-line defense
        # Defer the ``autonomous.log`` import to call time (same
        # rationale as ``observability.events.event``).
        from autonomous import log

        log(
            f"HttpClient hook {getattr(hook, '__name__', repr(hook))} raised "
            f"{type(hook_exc).__name__}: {hook_exc}",
        )


class HttpClient:
    """Reusable HTTP client with timeout + retry + transport-failure
    classification + observability hooks.

    Construct one per adapter; reuse across calls. Safe for concurrent
    request/response cycles (each call uses its own attempt-counter
    closure and ``requests.PreparedRequest``) provided no thread
    mutates the underlying ``requests.Session``'s attributes after
    construction. Observability hooks should be reentrant for the same
    reason; a hook exception is caught and logged so a buggy adapter
    hook never replaces the original transport-class exception (see
    ``_safe_hook``).

    Args:
        timeout: Default per-call timeout in seconds. Per-call
            ``timeout=`` overrides. ``None`` disables timeout (matches
            ``requests`` semantics) — avoid unless you have a hard
            external wall-clock cap.
        max_attempts: Retry budget. ``1`` (default) disables retry —
            each call is a single attempt. Counts the first attempt,
            so ``3`` = original + 2 retries.
        retry_backoff: Seconds to sleep between failed attempts.
            Passed through to ``autonomous.ai.retry.retry``.
        retry_jitter: Fraction in ``[0, 1)``. ``0.0`` keeps the legacy
            no-jitter shape; ``0.3`` smears retries by ±30% so many
            concurrent retriers don't wake in lockstep.
        transport_failure_codes: Status codes (beyond the ``>= 500``
            range) to classify as transport-class. ``{401}`` for HPC's
            revoked-token == VPN-drop equivalence; ``{408, 429}`` for
            throttle-aware adapters.
        transport_error_cls: Exception type raised on transport-class
            response or transport-class exception. Defaults to
            ``TransportError``. Adapters with a typed equivalent
            (``HPCUnreachableError``) pass it here so retry exhaustion
            re-raises the adapter-specific type.
        on_request: Hook fired before each attempt. Receives
            ``(method, url, headers, body)``. ``body`` is whichever of
            ``json``/``data``/``files`` was passed.
        on_response: Hook fired on every received response (including
            ones classified as transport-failure). Receives
            ``(method, url, response, attempt)`` where ``attempt`` is
            1-indexed.
        on_failure: Hook fired on every caught exception during an
            attempt. Receives ``(method, url, exc, attempt)``.
        session: Inject a pre-built ``requests.Session`` (tests use
            this with a mock adapter). Defaults to a fresh session.
    """

    def __init__(
        self,
        *,
        timeout: float | None = 30.0,
        max_attempts: int = 1,
        retry_backoff: float = 0.0,
        retry_jitter: float = 0.0,
        transport_failure_codes: Iterable[int] = (),
        transport_error_cls: type[Exception] = TransportError,
        on_request: RequestHook | None = None,
        on_response: ResponseHook | None = None,
        on_failure: FailureHook | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        self.retry_jitter = retry_jitter
        self.transport_failure_codes = frozenset(transport_failure_codes)
        self.transport_error_cls = transport_error_cls
        self.on_request: RequestHook = on_request or _noop_request
        self.on_response: ResponseHook = on_response or _noop_response
        self.on_failure: FailureHook = on_failure or _noop_failure
        self.session = session or requests.Session()

    def is_transport_failure(self, status: Any) -> bool:
        """Per-instance wrapper around the module-level predicate; uses
        ``self.transport_failure_codes`` as the extras set."""
        return is_transport_failure(status, extra_codes=self.transport_failure_codes)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        files: Any = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Run a request with retry + transport-failure classification.

        Returns the ``requests.Response`` on success (non-transport-
        class status). Raises ``self.transport_error_cls`` after retry
        exhaustion on transport-class status / exception. Re-raises
        config / programmer-error exception types raw (see
        ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS``).

        Any non-transport HTTP error (4xx other than configured extras)
        is surfaced via ``response.raise_for_status()`` so the caller
        gets a ``requests.HTTPError`` with the original response
        attached — matches existing adapter contracts.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        # Pick the request "body" for the on_request hook — whichever
        # of json/data/files was passed. Plain ``params`` (querystring)
        # is intentionally not a body.
        body_for_hook = json if json is not None else (data if data is not None else files)

        attempt_counter = [0]

        def _attempt() -> requests.Response:
            attempt_counter[0] += 1
            attempt = attempt_counter[0]
            _safe_hook(
                self.on_request,
                method,
                url,
                dict(headers) if headers else None,
                body_for_hook,
            )
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    timeout=effective_timeout,
                    **kwargs,
                )
            except _NON_TRANSPORT_REQUESTS_EXCEPTIONS:
                # Config error — don't burn the retry budget; let the
                # caller see the precise exception type. Notify the
                # failure hook so observability still records it.
                exc = _current_exc()
                _safe_hook(self.on_failure, method, url, exc, attempt)
                raise
            except requests.RequestException as exc:
                # Transport-class exception (connection, timeout,
                # chunked-encoding). Map to the configured transport
                # error type so the retry loop catches it.
                _safe_hook(self.on_failure, method, url, exc, attempt)
                raise self.transport_error_cls(
                    f"{method} {url} failed ({type(exc).__name__}): {exc}"
                ) from exc

            _safe_hook(self.on_response, method, url, response, attempt)
            if self.is_transport_failure(response.status_code):
                err = self.transport_error_cls(
                    f"{method} {url} returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                raise err
            response.raise_for_status()
            return response

        return retry(
            _attempt,
            max_attempts=self.max_attempts,
            sleep_seconds=self.retry_backoff,
            jitter=self.retry_jitter,
            catch=(self.transport_error_cls,),
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", url, **kwargs)

    def poll(
        self,
        fetch: Callable[[], Any],
        *,
        predicate: Callable[[Any], bool],
        max_attempts: int,
        sleep_seconds: float,
        jitter: float = 0.0,
    ) -> Any:
        """Poll ``fetch()`` until ``predicate(result)`` returns True
        or the attempt budget is exhausted.

        Designed to replace the bare ``while`` + ``time.sleep`` loops
        in ``ai.models.gemini.GeminiAIModel`` (README #6) — those loops
        currently have no wall-clock cap. ``poll`` enforces one.

        Returns the first ``result`` for which ``predicate(result)``
        is True. Raises ``TimeoutError`` after ``max_attempts``.

        ``fetch`` is invoked raw — no retry-wrapper, no transport-error
        classification, no observability hook firing. Callers that
        want those semantics should call ``self.request(...)`` inside
        ``fetch`` itself (e.g. ``fetch=lambda: self.get(file_url)``).
        Exceptions from ``fetch`` propagate immediately and do NOT
        count against ``max_attempts``.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        import time as _time

        last: Any = None
        for attempt in range(1, max_attempts + 1):
            last = fetch()
            if predicate(last):
                return last
            if attempt < max_attempts and sleep_seconds > 0:
                if jitter > 0:
                    import random as _random

                    actual = sleep_seconds * _random.uniform(1 - jitter, 1 + jitter)
                else:
                    actual = sleep_seconds
                _time.sleep(actual)
        raise TimeoutError(
            f"poll() exhausted {max_attempts} attempts without satisfying predicate; "
            f"last result: {last!r}"
        )


def _current_exc() -> BaseException:
    """Return the in-flight exception for the current ``except`` block.

    Wrapping ``sys.exc_info()[1]`` keeps the call site readable and
    quiets a type-checker false positive on the optionality (we only
    call this from inside an ``except`` clause, so it's never None).
    """
    import sys

    exc = sys.exc_info()[1]
    assert exc is not None, "_current_exc must be called from inside an except block"
    return exc
