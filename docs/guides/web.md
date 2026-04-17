# Web — Response, Session, SignedCookieSession

``autonomous.web`` is a tiny WSGI-compatible layer. It exists so the
auth and decorator pieces of Autonomous don't import Flask /
FastAPI / Starlette — you plug them into whatever host framework you
already have.

## Response

``Response`` implements both ``__iter__`` and the WSGI callable
``__call__(environ, start_response)``. It accepts string bodies,
byte bodies, or an iterable of chunks:

```python
from autonomous.web import Response

Response(body="hello")                # short; yields one chunk
Response(body=b"\x89PNG...", content_type="image/png")
Response(body=iter(lambda: fh.read(8192), b""))  # streams; chunked
Response(body=[b"a", b"b", b"c"])     # materialized list; three chunks
```

- A single bytes / str body is yielded as one chunk.
- An iterable is consumed chunk-by-chunk; ``str`` chunks are
  utf-8-encoded.
- An empty ``b""`` body still yields one ``b""`` chunk so WSGI
  servers see a finite iterable.

### Redirects

```python
from autonomous.web import redirect
return redirect("/next", status=303)
```

### Flask compatibility

Flask views can return a ``Response`` unchanged — Flask's WSGI
adapter honours the callable. FastAPI / Starlette can wrap it via
``StreamingResponse(iter_chunks(), ...)`` if needed.

## Session — ``bind_session``

Authorization uses a dict-like session reachable through
``bind_session``. Any mapping with ``__getitem__`` / ``__setitem__`` /
``get`` works:

```python
from autonomous.web import bind_session

bind_session(flask_session)           # Flask
bind_session(request.session)         # Starlette
bind_session(ContextSession())        # per-request dict (fallback)
```

### ContextSession

A ``dict`` subclass with a no-op ``save()`` for cases where you
genuinely just want an in-memory session for the duration of a
request:

```python
from autonomous.web import ContextSession
bind_session(ContextSession())
```

## SignedCookieSession

A stdlib-only signed-cookie session. Serializes a dict to a signed
JWT-like envelope suitable for a cookie:

```python
from autonomous.web import SignedCookieSession

secret = b"your-secret"

# Producer
sess = SignedCookieSession(secret, initial={"user_id": 42},
                           max_age=86400, issuer="myapp")
cookie_value = sess.to_cookie()

# Consumer
sess = SignedCookieSession.from_cookie(
    secret, request.cookies.get("session"),
    max_age=86400, issuer="myapp",
)
sess["user_id"]         # 42
```

### Claim handling

A reserved key ``__meta__`` inside the payload carries:

- ``iat`` — issued-at epoch seconds.
- ``exp`` — expiry epoch (if ``max_age`` set at mint).
- ``iss`` — issuer (if ``issuer`` set at mint).

The consumer rules:

- No ``max_age`` / no ``issuer`` on the consumer → no check
  (backward compatible with old cookies that lack ``__meta__``).
- ``max_age`` set → reject tokens missing or past ``exp``.
- ``issuer`` set → reject tokens missing or mismatching ``iss``.

Userland can still put whatever keys it wants in the dict;
``__meta__`` is stripped before ``dict.__iter__`` / ``.items()`` /
``.keys()`` see it.

### Why

The previous signed cookie was infinitely valid. With ``max_age`` you
can shrink the blast radius of a leaked signing key. With ``issuer``
you can keep app-A tokens from verifying in app-B sharing the same
secret.

## Wiring recap

| What | Default | How to override |
|------|---------|-----------------|
| Session store | none (must ``bind_session``) | ``bind_session(your_session)`` |
| Login URL | ``"/auth/login"`` | ``AutoAuth.login_url = "..."`` |
| OAuth state key | ``"oauth_state"`` | ``YourAuth.state_session_key = "..."`` |
| Throttle ``last_login`` | 60 s | ``AutoAuth.last_login_throttle_seconds = N`` |
