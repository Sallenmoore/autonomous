"""Independent committed coverage for PR #81 / issue #77.

PR #81 adds a ``max_attempts: int | None = None`` keyword to
``HttpClient.request`` (and by extension to all of ``.get`` / ``.post``
/ ``.put`` / ``.delete`` via ``**kwargs``). ``None`` preserves the
instance default; an integer override is used for that single call.
Must be ``>= 1``; ``<= 0`` raises ``ValueError("max_attempts must be
>= 1")``.

``FluxAIModel.generate_image`` passes ``max_attempts=1`` on the CDN
GET to short-circuit retry on a signed-URL 4xx (fal.ai signed URLs
that 4xx are permanently invalid — burning the retry budget against
them is pure latency waste).

Independent perspective (no peek at dev's ``tests/_dev_local/``):
- Signature: the keyword exists with the documented default and type.
- ``max_attempts=None`` preserves ``self.max_attempts``.
- ``max_attempts=N`` uses N attempts (observable via the underlying
  ``session.request`` call count under transient failure).
- ``max_attempts=1`` produces exactly one underlying attempt.
- ``max_attempts < 1`` raises ``ValueError`` BEFORE any request is
  attempted (pre-flight guard, not post-mortem).
- ``max_attempts`` works through ``.get`` (the convenience wrapper
  flux uses) — wrappers forward to ``request`` via ``**kwargs``.
- ``flux.generate_image`` actually passes ``max_attempts=1`` to its
  CDN GET (the end-to-end contract that motivated #77).
"""

import inspect

import pytest
import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status=200, content=b"", json_data=None, text=""):
        self.status_code = status
        self.content = content
        self._json = json_data or {}
        # ``text`` is read by HttpClient's transport-class error message
        # (``response.text[:200]``); without it the source raises
        # AttributeError outside the retry-catch tuple and the retry
        # loop never re-enters.
        self.text = text or f"simulated {status} body"

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _build_client(max_attempts=3):
    from autonomous.http import HttpClient
    return HttpClient(max_attempts=max_attempts, retry_backoff=0.0)


# ---------------------------------------------------------------------------
# 1) Signature pinning — the kwarg exists, is keyword-only-or-positional,
#    is typed ``int | None``, defaults to None.
# ---------------------------------------------------------------------------


def test_request_signature_has_max_attempts_with_default_none():
    """If a future refactor renames or repositions ``max_attempts``,
    flux's per-call override (and any other call site that adopts the
    idiom) silently breaks. Pin the contract."""
    from autonomous.http import HttpClient

    sig = inspect.signature(HttpClient.request)
    assert "max_attempts" in sig.parameters, (
        f"HttpClient.request must accept max_attempts kwarg; "
        f"got params {list(sig.parameters)}"
    )
    p = sig.parameters["max_attempts"]
    assert p.default is None, (
        f"max_attempts must default to None (preserves instance default); "
        f"got default={p.default!r}"
    )


# ---------------------------------------------------------------------------
# 2) max_attempts=None → uses self.max_attempts (instance default)
# ---------------------------------------------------------------------------


def test_max_attempts_none_uses_instance_default(monkeypatch):
    """Smoke: passing ``max_attempts=None`` explicitly (or omitting it)
    must use ``self.max_attempts``. Pre-#77 behavior is unchanged for
    every existing call site."""
    client = _build_client(max_attempts=4)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        # 500 → transport-class → retry-eligible
        return _FakeResponse(status=500)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.request("GET", "http://x")

    assert calls["count"] == 4, (
        f"omitted max_attempts must use the instance default (4); "
        f"got {calls['count']} attempts"
    )


# ---------------------------------------------------------------------------
# 3) max_attempts=N overrides instance default
# ---------------------------------------------------------------------------


def test_max_attempts_override_overrides_instance_default(monkeypatch):
    """Instance default is 5, per-call override is 2 — request should
    make 2 attempts, not 5."""
    client = _build_client(max_attempts=5)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        return _FakeResponse(status=500)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.request("GET", "http://x", max_attempts=2)

    assert calls["count"] == 2, (
        f"max_attempts=2 override must produce exactly 2 attempts; "
        f"got {calls['count']}"
    )


# ---------------------------------------------------------------------------
# 4) max_attempts=1 → single attempt (the fail-fast case flux uses)
# ---------------------------------------------------------------------------


def test_max_attempts_one_is_single_attempt(monkeypatch):
    """The flux CDN-GET use case: a signed-URL 4xx is permanent, so a
    single attempt is correct. ``max_attempts=1`` must produce exactly
    one underlying ``session.request`` call regardless of instance
    default."""
    client = _build_client(max_attempts=10)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        return _FakeResponse(status=503)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.request("GET", "http://x", max_attempts=1)

    assert calls["count"] == 1, (
        f"max_attempts=1 must produce exactly 1 attempt (no retry); "
        f"got {calls['count']}"
    )


# ---------------------------------------------------------------------------
# 5) max_attempts < 1 raises ValueError BEFORE the request fires
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [0, -1, -100])
def test_max_attempts_below_one_raises_valueerror(monkeypatch, bad_value):
    """The pre-flight guard. A nonsensical 0 or negative value is
    programmer error; raise immediately rather than silently producing
    a no-op call (or worse: looping forever via interaction with
    underlying retry semantics)."""
    client = _build_client(max_attempts=3)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        return _FakeResponse(status=200)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ValueError, match=r"max_attempts must be >= 1"):
        client.request("GET", "http://x", max_attempts=bad_value)

    assert calls["count"] == 0, (
        f"invalid max_attempts must reject BEFORE issuing the request; "
        f"got {calls['count']} attempts before the raise"
    )


# ---------------------------------------------------------------------------
# 6) max_attempts forwards through .get / .post convenience wrappers
# ---------------------------------------------------------------------------


def test_max_attempts_forwards_through_get_wrapper(monkeypatch):
    """``.get`` / ``.post`` / etc. are thin wrappers around ``request``
    via ``**kwargs``. flux uses ``_HTTP.get(image_url, ...,
    max_attempts=1)`` — the kwarg must thread through the convenience
    layer cleanly."""
    client = _build_client(max_attempts=8)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        return _FakeResponse(status=500)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.get("http://x", max_attempts=1)

    assert calls["count"] == 1, (
        f"max_attempts=1 via .get convenience wrapper must produce 1 "
        f"attempt; got {calls['count']}"
    )


def test_max_attempts_forwards_through_post_wrapper(monkeypatch):
    client = _build_client(max_attempts=8)

    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        return _FakeResponse(status=500)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.post("http://x", json={"k": "v"}, max_attempts=1)

    assert calls["count"] == 1


# ---------------------------------------------------------------------------
# 7) flux.generate_image actually passes max_attempts=1 to its CDN GET
# ---------------------------------------------------------------------------


def _flux_instance():
    from autonomous.ai.models.flux import FluxAIModel
    return FluxAIModel.__new__(FluxAIModel)


def test_flux_cdn_get_passes_max_attempts_one(monkeypatch):
    """The whole motivation for #77 was flux's CDN GET burning the
    retry budget on a signed-URL 4xx. End-to-end pin: when flux calls
    out to fetch the image bytes, it MUST pass ``max_attempts=1`` so
    the HttpClient short-circuits retry for that leg specifically.

    The POST (still using the full ``settings.flux_max_attempts``
    budget) is NOT subject to this — only the CDN GET. The test asserts
    the GET kwargs include ``max_attempts=1`` AND that the POST kwargs
    do NOT include ``max_attempts=1`` (so we don't silently regress the
    fal.ai POST path too, which still wants retry on transient 5xx)."""
    monkeypatch.setenv("FAL_KEY", "fal-test-key")

    captured = {"post_kwargs": None, "get_kwargs": None}

    def fake_post(url, **kwargs):
        captured["post_kwargs"] = kwargs
        return _FakeResponse(json_data={"images": [{"url": "https://cdn/x.webp"}]})

    def fake_get(url, **kwargs):
        captured["get_kwargs"] = kwargs
        return _FakeResponse(content=b"\x89PNG-bytes")

    from autonomous.ai.models import flux as flux_mod
    monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)
    monkeypatch.setattr(flux_mod._HTTP, "get", fake_get)

    result = flux_mod.FluxAIModel.generate_image(_flux_instance(), "a prompt")
    assert result == b"\x89PNG-bytes"

    # CDN GET must carry max_attempts=1.
    assert captured["get_kwargs"] is not None, "flux did not call _HTTP.get"
    assert captured["get_kwargs"].get("max_attempts") == 1, (
        f"flux's CDN GET must pass max_attempts=1 to short-circuit retry "
        f"on signed-URL 4xx; got kwargs={captured['get_kwargs']!r}"
    )

    # POST must NOT carry max_attempts=1 — the fal.ai POST still gets
    # the full settings.flux_max_attempts retry budget.
    assert captured["post_kwargs"] is not None, "flux did not call _HTTP.post"
    assert captured["post_kwargs"].get("max_attempts") != 1, (
        f"flux's fal.ai POST must NOT silently regress to single-attempt; "
        f"#77 scopes the override to the CDN GET only; got "
        f"kwargs={captured['post_kwargs']!r}"
    )


# ---------------------------------------------------------------------------
# 8) Happy path: instance default unchanged when override absent
# ---------------------------------------------------------------------------


def test_instance_default_unchanged_when_override_absent(monkeypatch):
    """Regression guard — a per-call override must not silently mutate
    ``self.max_attempts``."""
    client = _build_client(max_attempts=3)
    original = client.max_attempts

    def fake_request(method, url, **kwargs):
        return _FakeResponse(status=200)

    monkeypatch.setattr(client.session, "request", fake_request)

    client.request("GET", "http://x", max_attempts=1)
    assert client.max_attempts == original, (
        f"per-call max_attempts override must not mutate instance state; "
        f"was {original}, now {client.max_attempts}"
    )
