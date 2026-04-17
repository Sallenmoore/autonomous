import pytest

from autonomous.web import (
    ContextSession,
    Response,
    SignedCookieSession,
    bind_session,
    clear_session,
    get_session,
    redirect,
)


class TestResponse:
    def test_default_response(self):
        r = Response()
        assert r.status == 200
        assert r.body == b""
        assert r.headers == {}

    def test_body_encoded_from_str(self):
        r = Response(body="hello")
        assert r.body == b"hello"

    def test_status_line(self):
        assert Response(status=200).status_line == "200 OK"
        assert Response(status=302).status_line == "302 Found"
        assert Response(status=404).status_line == "404 Not Found"

    def test_header_list(self):
        r = Response(headers={"X-Foo": "bar", "Content-Type": "text/plain"})
        pairs = dict(r.header_list())
        assert pairs["X-Foo"] == "bar"
        assert pairs["Content-Type"] == "text/plain"

    def test_wsgi_callable(self):
        r = Response(status=201, headers={"Location": "/x"}, body=b"hi")
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        body = r({}, start_response)
        assert captured["status"] == "201 Created"
        assert ("Location", "/x") in captured["headers"]
        assert body == [b"hi"]

    def test_iterable(self):
        chunks = list(Response(body=b"abc"))
        assert chunks == [b"abc"]


class TestRedirect:
    def test_redirect_default_302(self):
        r = redirect("/login")
        assert r.status == 302
        assert r.headers["Location"] == "/login"

    def test_redirect_custom_status(self):
        r = redirect("/new", status=301)
        assert r.status == 301
        assert r.headers["Location"] == "/new"


class TestContextSession:
    def test_roundtrip_within_context(self):
        store = ContextSession()
        token = bind_session(store)
        try:
            get_session()["user"] = "bob"
            assert get_session().get("user") == "bob"
            assert "user" in get_session()
        finally:
            clear_session(token)

    def test_default_session_is_fresh(self):
        clear_session()
        s1 = get_session()
        s1["x"] = 1
        clear_session()
        s2 = get_session()
        assert "x" not in s2


class TestSignedCookieSession:
    secret = "s3cret-key"

    def test_roundtrip(self):
        s = SignedCookieSession(self.secret, {"user": "alice", "n": 3})
        token = s.dumps()
        loaded = SignedCookieSession.from_cookie(self.secret, token)
        assert loaded["user"] == "alice"
        assert loaded["n"] == 3

    def test_rejects_tampered_payload(self):
        s = SignedCookieSession(self.secret, {"admin": False})
        token = s.dumps()
        payload_b64, sig_b64 = token.split(".", 1)
        tampered = payload_b64 + "A" + "." + sig_b64
        loaded = SignedCookieSession.from_cookie(self.secret, tampered)
        assert dict(loaded) == {}

    def test_rejects_tampered_signature(self):
        s = SignedCookieSession(self.secret, {"admin": False})
        token = s.dumps()
        payload_b64, sig_b64 = token.split(".", 1)
        tampered = payload_b64 + "." + sig_b64[:-2] + "AA"
        loaded = SignedCookieSession.from_cookie(self.secret, tampered)
        assert dict(loaded) == {}

    def test_rejects_wrong_secret(self):
        token = SignedCookieSession(self.secret, {"user": "alice"}).dumps()
        loaded = SignedCookieSession.from_cookie("other-secret", token)
        assert dict(loaded) == {}

    def test_empty_secret_rejected(self):
        with pytest.raises(ValueError):
            SignedCookieSession("")

    def test_from_cookie_with_none_token(self):
        s = SignedCookieSession.from_cookie(self.secret, None)
        assert dict(s) == {}

    def test_from_cookie_with_malformed_token(self):
        s = SignedCookieSession.from_cookie(self.secret, "not-a-valid-token")
        assert dict(s) == {}


class TestSignedCookieSessionExpiry:
    """Item 15: optional ``max_age`` attaches an ``exp`` claim and the
    consumer rejects expired or missing-exp tokens."""

    secret = "exp-key"

    def test_within_window_loads_normally(self):
        token = SignedCookieSession(
            self.secret, {"user": "alice"}, max_age=3600
        ).dumps()
        loaded = SignedCookieSession.from_cookie(
            self.secret, token, max_age=3600
        )
        assert loaded["user"] == "alice"
        # Reserved meta key must never leak into the dict.
        assert "__meta__" not in loaded

    def test_past_exp_rejects(self, monkeypatch):
        # Mint at t=1000.
        monkeypatch.setattr("autonomous.web.session.time.time", lambda: 1000)
        token = SignedCookieSession(
            self.secret, {"user": "alice"}, max_age=10
        ).dumps()
        # Verify at t=2000 (well past 1010).
        monkeypatch.setattr("autonomous.web.session.time.time", lambda: 2000)
        loaded = SignedCookieSession.from_cookie(self.secret, token)
        assert dict(loaded) == {}

    def test_consumer_requires_exp_but_token_has_none(self):
        # Old-style token without max_age -> no exp claim.
        legacy_token = SignedCookieSession(
            self.secret, {"user": "alice"}
        ).dumps()
        # Consumer that *requires* expiry must reject (downgrade defense).
        loaded = SignedCookieSession.from_cookie(
            self.secret, legacy_token, max_age=3600
        )
        assert dict(loaded) == {}

    def test_legacy_consumer_accepts_legacy_token(self):
        """Backward-compat: neither side configured max_age/issuer."""
        legacy_token = SignedCookieSession(
            self.secret, {"user": "alice"}
        ).dumps()
        loaded = SignedCookieSession.from_cookie(self.secret, legacy_token)
        assert loaded["user"] == "alice"


class TestSignedCookieSessionIssuer:
    """Item 15: optional ``issuer`` pin guards against cross-app token reuse."""

    secret = "iss-key"

    def test_matching_issuer_loads(self):
        token = SignedCookieSession(
            self.secret, {"user": "alice"}, issuer="my-app"
        ).dumps()
        loaded = SignedCookieSession.from_cookie(
            self.secret, token, issuer="my-app"
        )
        assert loaded["user"] == "alice"

    def test_mismatched_issuer_rejected(self):
        token = SignedCookieSession(
            self.secret, {"user": "alice"}, issuer="app-a"
        ).dumps()
        loaded = SignedCookieSession.from_cookie(
            self.secret, token, issuer="app-b"
        )
        assert dict(loaded) == {}

    def test_consumer_requires_issuer_but_token_has_none(self):
        legacy_token = SignedCookieSession(
            self.secret, {"user": "alice"}
        ).dumps()
        loaded = SignedCookieSession.from_cookie(
            self.secret, legacy_token, issuer="my-app"
        )
        assert dict(loaded) == {}

    def test_token_carries_issuer_but_consumer_doesnt_check(self):
        token = SignedCookieSession(
            self.secret, {"user": "alice"}, issuer="my-app"
        ).dumps()
        # Consumer with no issuer set ignores the iss field.
        loaded = SignedCookieSession.from_cookie(self.secret, token)
        assert loaded["user"] == "alice"


class TestSignedCookieSessionMetaIsolation:
    secret = "meta-key"

    def test_meta_key_in_user_data_is_dropped_on_dump(self):
        """If a caller stores ``__meta__`` in their session it must not
        clobber the envelope metadata."""
        s = SignedCookieSession(
            self.secret, {"user": "alice", "__meta__": "evil"}, max_age=60
        )
        token = s.dumps()
        loaded = SignedCookieSession.from_cookie(
            self.secret, token, max_age=60
        )
        assert loaded["user"] == "alice"
        assert "__meta__" not in loaded
