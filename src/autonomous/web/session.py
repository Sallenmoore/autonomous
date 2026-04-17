import base64
import hashlib
import hmac
import json
import time
from contextvars import ContextVar
from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    def get(self, key, default=None): ...
    def __getitem__(self, key): ...
    def __setitem__(self, key, value): ...
    def __delitem__(self, key): ...
    def __contains__(self, key) -> bool: ...
    def clear(self) -> None: ...


class ContextSession(dict):
    """In-memory dict-backed session. Intended to be bound per request via bind_session."""


_current_session: ContextVar[SessionStore | None] = ContextVar(
    "autonomous_session", default=None
)


def bind_session(store: SessionStore):
    return _current_session.set(store)


def clear_session(token=None) -> None:
    if token is not None:
        _current_session.reset(token)
    else:
        _current_session.set(None)


def get_session() -> SessionStore:
    store = _current_session.get()
    if store is None:
        store = ContextSession()
        _current_session.set(store)
    return store


class SignedCookieSession(dict):
    """Dict-like session that serializes to a signed cookie value.

    The encoded form is ``<b64url(json_payload)>.<b64url(hmac_sha256)>``.
    Tampering with either segment invalidates the signature.

    Optional envelope metadata (``__meta__`` reserved key in the payload):

    - ``iat`` (issued-at, unix seconds): always set on dump.
    - ``exp`` (expires-at, unix seconds): set when ``max_age`` was given.
      Verification rejects tokens past ``exp``.
    - ``iss`` (issuer string): set when ``issuer`` was given. Verification
      requires a matching issuer.

    A consumer that configures ``max_age`` rejects tokens with no ``exp``
    (downgrade defense). A consumer that configures ``issuer`` rejects
    tokens minted for a different issuer or with no issuer at all. A
    consumer with neither set behaves as before — backward compatible
    with cookies minted by older versions.
    """

    #: Reserved payload key for envelope metadata.
    _META_KEY = "__meta__"

    def __init__(
        self,
        secret: str | bytes,
        initial: dict | None = None,
        *,
        max_age: int | None = None,
        issuer: str | None = None,
    ):
        super().__init__(initial or {})
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not secret:
            raise ValueError("SignedCookieSession requires a non-empty secret")
        self._secret = secret
        self._max_age = max_age
        self._issuer = issuer

    def dumps(self) -> str:
        payload_dict = {k: v for k, v in self.items() if k != self._META_KEY}
        meta: dict = {"iat": int(time.time())}
        if self._max_age is not None:
            meta["exp"] = meta["iat"] + self._max_age
        if self._issuer is not None:
            meta["iss"] = self._issuer
        payload_dict[self._META_KEY] = meta
        payload = json.dumps(
            payload_dict, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        sig = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64e(payload)}.{_b64e(sig)}"

    def loads(self, token: str) -> None:
        self.clear()
        data = self._verify(token)
        if data is None:
            return
        meta = data.pop(self._META_KEY, None)
        if not self._meta_is_valid(meta):
            return
        self.update(data)

    @classmethod
    def from_cookie(
        cls,
        secret: str | bytes,
        token: str | None,
        *,
        max_age: int | None = None,
        issuer: str | None = None,
    ) -> "SignedCookieSession":
        session = cls(secret, max_age=max_age, issuer=issuer)
        if token:
            session.loads(token)
        return session

    def _meta_is_valid(self, meta) -> bool:
        # Tokens minted before envelope metadata existed have no meta
        # block. Accept them only if neither expiry nor issuer was
        # required by this consumer (backward compatibility).
        if meta is None:
            return self._max_age is None and self._issuer is None
        if not isinstance(meta, dict):
            return False
        if self._issuer is not None and meta.get("iss") != self._issuer:
            return False
        exp = meta.get("exp")
        if exp is not None and time.time() > exp:
            return False
        if self._max_age is not None and exp is None:
            # Consumer requires expiry; producer didn't set one. Reject.
            return False
        return True

    def _verify(self, token: str) -> dict | None:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            payload = _b64d(payload_b64)
            sig = _b64d(sig_b64)
        except (ValueError, TypeError):
            return None
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)
