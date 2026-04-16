import base64
import hashlib
import hmac
import json
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
    """

    def __init__(self, secret: str | bytes, initial: dict | None = None):
        super().__init__(initial or {})
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not secret:
            raise ValueError("SignedCookieSession requires a non-empty secret")
        self._secret = secret

    def dumps(self) -> str:
        payload = json.dumps(dict(self), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        sig = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64e(payload)}.{_b64e(sig)}"

    def loads(self, token: str) -> None:
        self.clear()
        data = self._verify(token)
        if data is not None:
            self.update(data)

    @classmethod
    def from_cookie(
        cls, secret: str | bytes, token: str | None
    ) -> "SignedCookieSession":
        session = cls(secret)
        if token:
            session.loads(token)
        return session

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
