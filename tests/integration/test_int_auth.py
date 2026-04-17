"""
Unit tests for the auth layer after Flask removal.

These tests exercise the decorator / session plumbing in ``AutoAuth`` and the
``GithubAuth`` / ``GoogleAuth`` subclasses without hitting the network or a
real database. MongoDB, OAuth endpoints, and user persistence are all mocked.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_AUTH_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_AUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("GOOGLE_AUTH_REDIRECT_URL", "http://localhost/cb")
    monkeypatch.setenv("GOOGLE_DISCOVERY_URL", "http://discovery.example/oidc")
    monkeypatch.setenv("GITHUB_AUTH_CLIENT_ID", "test-gh-id")
    monkeypatch.setenv("GITHUB_AUTH_CLIENT_SECRET", "test-gh-secret")
    monkeypatch.setenv("GITHUB_AUTH_REDIRECT_URL", "http://localhost/cb")
    monkeypatch.setenv(
        "GITHUB_AUTH_AUTHORIZE_URL", "https://github.example/login/oauth/authorize"
    )
    monkeypatch.setenv(
        "GITHUB_AUTH_TOKEN_URL", "https://github.example/login/oauth/access_token"
    )


class TestGithubAuth:
    def test_authenticate_returns_uri_and_state(self):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        uri, state = auth.authenticate()
        assert uri.startswith("https://github.example/login/oauth/authorize")
        assert "client_id=test-gh-id" in uri
        assert state


class TestGoogleAuth:
    def test_authenticate_fetches_discovery_and_returns_uri(self):
        discovery = {
            "authorization_endpoint": "https://accounts.example/o/oauth2/auth",
            "token_endpoint": "https://oauth2.example/token",
        }
        with patch(
            "autonomous.auth.google.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=discovery)),
        ):
            from autonomous.auth.google import GoogleAuth

            auth = GoogleAuth()
            uri, state = auth.authenticate()
        assert uri.startswith("https://accounts.example/o/oauth2/auth")
        assert "client_id=test-google-id" in uri
        assert state


class _FakeUser:
    """Lightweight stand-in for autonomous.auth.user.User."""

    def __init__(
        self,
        pk=1,
        state="authenticated",
        role="user",
        is_guest=False,
        is_admin=False,
    ):
        self.pk = pk
        self.state = state
        self.role = role
        self._is_guest = is_guest
        self._is_admin = is_admin
        self.last_login = None
        self.saved = False

    @property
    def is_guest(self):
        return self._is_guest

    @property
    def is_admin(self):
        return self._is_admin

    def save(self):
        self.saved = True
        return self.pk

    def to_json(self):
        return f'{{"pk": {self.pk}, "state": "{self.state}"}}'


class _FakeUserClass:
    current = None
    guest = _FakeUser(pk=0, state="guest", role="guest", is_guest=True)

    @classmethod
    def get(cls, pk):
        return cls.current

    @classmethod
    def from_json(cls, blob):
        return cls.current

    @classmethod
    def get_guest(cls):
        return cls.guest


@pytest.fixture
def auth_cls():
    from autonomous.auth.autoauth import AutoAuth

    original = AutoAuth.user_class
    AutoAuth.user_class = _FakeUserClass
    yield AutoAuth
    AutoAuth.user_class = original
    _FakeUserClass.current = None


@pytest.fixture
def bound_session():
    from autonomous.web import ContextSession, bind_session, clear_session

    store = ContextSession()
    token = bind_session(store)
    yield store
    clear_session(token)


class TestCurrentUser:
    def test_returns_guest_when_no_session_user(self, auth_cls, bound_session):
        user = auth_cls.current_user()
        assert user is _FakeUserClass.guest

    def test_returns_session_user_when_authenticated(self, auth_cls, bound_session):
        fake = _FakeUser(pk=42, state="authenticated")
        _FakeUserClass.current = fake
        bound_session["user"] = fake.to_json()
        user = auth_cls.current_user()
        assert user is fake

    def test_pk_lookup_returns_guest_when_unauthenticated(
        self, auth_cls, bound_session
    ):
        _FakeUserClass.current = _FakeUser(pk=7, state="unauthenticated")
        user = auth_cls.current_user(pk=7)
        assert user is _FakeUserClass.guest


class TestAuthRequired:
    def test_redirects_unauthenticated_guest(self, auth_cls, bound_session):
        @auth_cls.auth_required()
        def view():
            return "ok"

        response = view()
        assert response.status == 302
        assert response.headers["Location"] == auth_cls.login_url

    def test_passes_through_authenticated_user(self, auth_cls, bound_session):
        fake = _FakeUser(pk=1, state="authenticated")
        _FakeUserClass.current = fake
        bound_session["user"] = fake.to_json()

        @auth_cls.auth_required()
        def view():
            return "hello"

        assert view() == "hello"
        assert _FakeUserClass.current.saved is True
        assert bound_session["user"] == _FakeUserClass.current.to_json()

    def test_admin_only_rejects_non_admin(self, auth_cls, bound_session):
        _FakeUserClass.current = _FakeUser(
            pk=1, state="authenticated", is_admin=False
        )

        @auth_cls.auth_required(admin=True)
        def view():
            return "admin"

        response = view()
        assert response.status == 302
        assert response.headers["Location"] == auth_cls.login_url

    def test_admin_only_allows_admin(self, auth_cls, bound_session):
        fake = _FakeUser(
            pk=1, state="authenticated", role="admin", is_admin=True
        )
        _FakeUserClass.current = fake
        bound_session["user"] = fake.to_json()

        @auth_cls.auth_required(admin=True)
        def view():
            return "admin"

        assert view() == "admin"

    def test_guest_flag_allows_guest(self, auth_cls, bound_session):
        # When guest=True, a guest user should still pass through.
        _FakeUserClass.current = _FakeUser(
            pk=0, state="guest", role="guest", is_guest=True
        )

        @auth_cls.auth_required(guest=True)
        def view():
            return "welcome"

        assert view() == "welcome"

    def test_configurable_login_url(self, auth_cls, bound_session):
        original = auth_cls.login_url
        auth_cls.login_url = "/custom/login"
        try:

            @auth_cls.auth_required()
            def view():
                return "ok"

            assert view().headers["Location"] == "/custom/login"
        finally:
            auth_cls.login_url = original
