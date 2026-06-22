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

import math
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


class _NonTransportHTTPError(Exception):
    """Internal marker (#91): wraps ``response.raise_for_status``-raised
    ``requests.HTTPError`` so the retry catch tuple never matches it,
    regardless of what ``transport_error_cls`` an adapter picked.

    Pre-#91, ``HttpClient.request`` set the retry catch tuple to
    ``(self.transport_error_cls,)``. When an adapter passed
    ``transport_error_cls=requests.RequestException`` (the natural
    choice for downstream-catch compatibility — every legacy adapter
    did ``except requests.RequestException``), the retry tuple caught
    ``requests.HTTPError`` too because ``HTTPError`` is a
    ``RequestException`` subclass. The result: non-transport 4xx
    responses burned the full retry budget before propagating, defeating
    fail-fast semantics for permanent client errors.

    The fix wraps the HTTPError inside ``_attempt`` so the class that
    propagates out of ``_attempt`` (a) is NOT a ``transport_error_cls``
    subclass (the catch tuple never matches), and (b) carries the
    original on ``self.original`` (NOT ``__cause__`` — the construction
    site uses bare ``raise _NonTransportHTTPError(exc)`` without
    ``from exc`` because the marker is unwrapped at the boundary before
    any chain-walker observes it). ``HttpClient.request`` catches the
    wrapper at the boundary and re-raises the original ``HTTPError``
    via ``raise ... from None``, so callers see exactly the type they
    saw pre-#91 (``except requests.RequestException``-style catches
    keep working). The marker class is private — consumers should
    never see it.

    See issue #91. Supersedes the flux-local workaround #85.
    """

    def __init__(self, original: requests.HTTPError) -> None:
        # No-arg ``super().__init__()`` — the marker never surfaces to
        # a caller's traceback, so a string message would be unused
        # work. Defensive guard: reject ``None`` up front. The single
        # in-tree construction site (``_attempt`` below) can't actually
        # pass None (Python's ``except as exc`` guarantees non-None),
        # but a future call site that misuses the marker would
        # otherwise produce ``TypeError: exceptions must derive from
        # BaseException`` at the unwrap site with no breadcrumb back
        # here.
        if original is None:
            raise TypeError(
                "_NonTransportHTTPError requires a non-None requests.HTTPError"
            )
        super().__init__()
        self.original = original


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
        timeout: Default per-call timeout in seconds, or a
            ``(connect, read)`` tuple to budget the two phases
            independently (``requests``-native shape). Per-call
            ``timeout=`` overrides. ``None`` disables timeout (matches
            ``requests`` semantics) — avoid unless you have a hard
            external wall-clock cap. The tuple form is the recommended
            shape for backends that may accept a connection and then
            stall mid-response (see openai_compat's HPC client + #177);
            a small connect-leg lets a dropped VPN fail fast while a
            bounded read-leg caps backend-stall worker pin time.
        max_attempts: Retry budget. ``1`` (default) disables retry —
            each call is a single attempt. Counts the first attempt,
            so ``3`` = original + 2 retries.
        retry_backoff: Seconds to sleep between failed attempts.
            Passed through to ``autonomous.ai.retry.retry`` as the base
            sleep.
        retry_backoff_factor: Geometric growth base for the inter-attempt
            sleep, passed through to ``autonomous.ai.retry.retry``.
            ``1.0`` (default) keeps the legacy flat backoff — every gap
            is exactly ``retry_backoff`` — so existing adapters are
            unaffected. ``2.0`` yields exponential backoff
            (``retry_backoff``, ``2×``, ``4×``, …) so a client can ride
            out a longer transient-degradation window without inflating
            ``max_attempts`` on the fast path (issue #182, the HPC
            ReadTimeout case). Must be ``>= 1.0``.
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
        timeout: float | tuple[float, float] | None = 30.0,
        max_attempts: int = 1,
        retry_backoff: float = 0.0,
        retry_backoff_factor: float = 1.0,
        retry_jitter: float = 0.0,
        transport_failure_codes: Iterable[int] = (),
        transport_error_cls: type[Exception] = TransportError,
        extra_non_transport_exceptions: Iterable[type[BaseException]] = (),
        on_request: RequestHook | None = None,
        on_response: ResponseHook | None = None,
        on_failure: FailureHook | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        # Fail-fast on an over-broad ``transport_error_cls`` (#98). #91's
        # ``_NonTransportHTTPError`` marker relies on NOT being a subclass
        # of any plausible ``transport_error_cls`` so the retry catch
        # tuple never matches it. A lazy ``transport_error_cls=Exception``
        # (or ``BaseException``) breaks that invariant: ``(Exception,)``
        # DOES catch the marker, so a permanent 4xx would burn the full
        # ``max_attempts`` budget — silently re-introducing the exact
        # retry-on-4xx bug #91 fixed. Reject at construction rather than
        # let it regress at runtime.
        if issubclass(_NonTransportHTTPError, transport_error_cls):
            raise ValueError(
                f"transport_error_cls={transport_error_cls.__name__} is too "
                f"broad: it would catch HttpClient's internal "
                f"_NonTransportHTTPError marker (see #91), re-introducing the "
                f"retry-on-4xx bug. Use a narrower class such as "
                f"requests.RequestException, requests.ConnectionError, or a "
                f"RuntimeError subclass."
            )
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        # Validate eagerly at construction (mirrors the ``max_attempts``
        # check above) rather than deferring to the first ``retry()``
        # call deep inside ``request()`` — a misconfigured
        # ``retry_backoff_factor`` should fail at adapter import, not on
        # the first transient failure in prod. ``retry()`` re-validates
        # too, but a module-level ``HttpClient(...)`` constant (the usual
        # shape — see ``openai_compat._HTTP``) gets caught at import.
        if not math.isfinite(retry_backoff_factor) or retry_backoff_factor < 1.0:
            raise ValueError("retry_backoff_factor must be a finite float >= 1.0")
        self.retry_backoff_factor = retry_backoff_factor
        self.retry_jitter = retry_jitter
        self.transport_failure_codes = frozenset(transport_failure_codes)
        self.transport_error_cls = transport_error_cls
        # Per-instance extension of ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS``
        # for adapters with deployment-specific config-class exceptions
        # (e.g. ``openai_compat`` carves out ``SSLError`` and ``ProxyError``
        # because in its HPC deployment they're corporate-cert-bundle /
        # corporate-proxy misconfigs that retry-with-translation
        # actively misdirects on-call). Most adapters leave this empty —
        # the module-level tuple already covers the universally
        # config-class ones (MissingSchema, InvalidURL, etc.).
        self._non_transport_exceptions: tuple[type[BaseException], ...] = (
            _NON_TRANSPORT_REQUESTS_EXCEPTIONS
            + tuple(extra_non_transport_exceptions)
        )
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
        timeout: float | tuple[float, float] | None = None,
        max_attempts: int | None = None,
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

        ``max_attempts`` overrides ``self.max_attempts`` for this call
        only. Pass ``max_attempts=1`` to disable retry for a single
        leg of a multi-step request (e.g. an adapter that retries a
        primary POST but should NOT retry the follow-up CDN GET because
        a signed-URL 4xx is permanent — issue #77, ``flux.generate_image``).
        ``None`` falls back to the instance default. Must be ``>= 1``.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        effective_max_attempts = (
            max_attempts if max_attempts is not None else self.max_attempts
        )
        if effective_max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
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
            except self._non_transport_exceptions:
                # Config error — don't burn the retry budget; let the
                # caller see the precise exception type. Notify the
                # failure hook so observability still records it.
                # Tuple is built per-instance: the module-level
                # ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` plus any
                # ``extra_non_transport_exceptions=`` passed at
                # construction time.
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
                # Defensive ``.text`` read — a 5xx body whose declared
                # charset can't decode would otherwise re-raise
                # ``UnicodeDecodeError`` inside the constructor arg,
                # masking ``transport_error_cls`` and bypassing the
                # ``on_failure`` hook below. Same defect class as #90
                # fixed in ``MalformedResponseError.from_response``;
                # #96 made this branch's error construction observable
                # for the first time, surfacing the latent hole.
                try:
                    excerpt = response.text[:200]
                except UnicodeDecodeError:
                    excerpt = response.content[:200].decode(
                        "utf-8", errors="replace"
                    )
                err = self.transport_error_cls(
                    f"{method} {url} returned {response.status_code}: "
                    f"{excerpt}"
                )
                # Fire on_failure for parity with the RequestException and
                # HTTPError branches (#96). Pre-#96 this transport-status
                # branch (5xx + configured extras) raised without notifying
                # the hook, so an adapter wiring ``on_failure=`` to an
                # alerting counter saw 4xx events (via #91's HTTPError
                # branch) but NOT 5xx — exactly inverted from what a
                # transport-degradation alert wants. Closes the
                # "pre-existing asymmetry ... tracked as a follow-up"
                # caveat in MIGRATIONS' #91 entry.
                _safe_hook(self.on_failure, method, url, err, attempt)
                raise err
            # Non-transport HTTP errors (4xx that aren't in
            # ``transport_failure_codes``) must never be retried — they
            # represent permanent client errors (bad request, auth not
            # configured for this resource, resource not found, signed
            # URL expired, etc.). Pre-#91 the bare ``raise_for_status()``
            # raised ``requests.HTTPError``, and the retry catch tuple
            # ``(self.transport_error_cls,)`` matched it whenever the
            # adapter picked ``transport_error_cls=requests.RequestException``
            # (because HTTPError is-a RequestException) — silently
            # burning the retry budget on permanent failures.
            #
            # Wrap the HTTPError in a private marker class that is NOT
            # a subclass of any plausible ``transport_error_cls``, so
            # the retry catch never matches it. ``request()`` unwraps
            # at the boundary so the caller still sees the original
            # ``requests.HTTPError`` — preserving the documented
            # contract ("Any non-transport HTTP error ... is surfaced
            # via response.raise_for_status() so the caller gets a
            # requests.HTTPError with the original response attached").
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                _safe_hook(self.on_failure, method, url, exc, attempt)
                # No ``from exc``: the marker is discarded at the unwrap
                # site (only ``wrapper.original`` is read), so its
                # ``__cause__`` chain is never observed.
                raise _NonTransportHTTPError(exc)
            return response

        # Capture the unwrapped HTTPError to a local. ``wrapper`` is
        # deleted at the end of the except clause (Python 3 except-as
        # semantics), but the captured local survives. Raising the
        # original from OUTSIDE the except block (next statement) means
        # there is no active exception when ``raise captured from None``
        # runs — so Python does NOT set ``captured.__context__`` to the
        # marker class. Pre-existing review concern (the marker was
        # leaking through ``__context__`` to sentry-style programmatic
        # introspection even though ``__suppress_context__`` hid it
        # from default tracebacks) is closed.
        captured_http_error: requests.HTTPError | None = None
        # Only forward ``backoff_factor`` when it's the non-default
        # exponential value. ``backoff_factor=1.0`` is a true no-op in
        # ``retry()`` (each gap is multiplied by ``1.0 ** (n-1) == 1``),
        # so omitting it for flat-backoff clients (every adapter except
        # the opted-in HPC client) leaves the call signature — and thus
        # the observed behavior — byte-identical to pre-#182. The
        # conditional keeps the common call site minimal rather than
        # threading a parameter that can't change anything.
        retry_kwargs: dict[str, Any] = {}
        if self.retry_backoff_factor != 1.0:
            retry_kwargs["backoff_factor"] = self.retry_backoff_factor
        try:
            result = retry(
                _attempt,
                max_attempts=effective_max_attempts,
                sleep_seconds=self.retry_backoff,
                jitter=self.retry_jitter,
                catch=(self.transport_error_cls,),
                **retry_kwargs,
            )
        except _NonTransportHTTPError as wrapper:
            captured_http_error = wrapper.original
        else:
            # Defensive escape guard (#103). The marker is RAISED inside
            # ``_attempt``, never returned, so ``result`` is always a
            # ``requests.Response`` and this isinstance check is
            # unreachable today. It pins the "marker never escapes
            # ``request()``" invariant in the type, not just in code
            # organization: a future refactor that moved the ``retry()``
            # call into a helper without preserving the unwrap above — or
            # that routed the marker as a value — would otherwise hand
            # callers an ``Exception``-typed marker where their
            # ``except requests.HTTPError`` expects an HTTPError, silently
            # breaking the #91 contract. Surface it at the boundary by
            # unwrapping to the original instead of letting it leak.
            if isinstance(result, _NonTransportHTTPError):  # pragma: no cover
                raise result.original from None
            return result
        # Outside the except clause — no active exception. ``from None``
        # additionally suppresses the marker's brief lifetime from any
        # display layer. Callers see exactly the requests.HTTPError
        # they saw pre-#91, with no marker class leakage on any
        # introspection surface (traceback or programmatic).
        raise captured_http_error from None

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
