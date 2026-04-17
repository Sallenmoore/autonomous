"""Item 6 + 19: OAuth state CSRF-protection tests.

Cover the contract:

- ``authenticate()`` rotates ``self.state`` on every call and stores the
  issued nonce in the active session under ``state_session_key``.
- ``handle_response()`` reads the expected state from the session if the
  caller doesn't pass one and refuses callbacks with no stored state
  (``MismatchingStateError``).
- The session entry is cleared whether the exchange succeeded or failed.
- An explicit ``state=`` arg overrides the session value.
"""

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


@pytest.fixture
def bound_session():
    from autonomous.web import ContextSession, bind_session, clear_session

    store = ContextSession()
    token = bind_session(store)
    yield store
    clear_session(token)


class TestAuthenticateStoresState:
    def test_state_written_to_session(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        uri, state = auth.authenticate()
        assert bound_session["oauth_state"] == state
        assert state in uri  # authlib embeds it in the redirect URL

    def test_state_rotates_on_each_call(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        _, s1 = auth.authenticate()
        _, s2 = auth.authenticate()
        assert s1 != s2
        assert bound_session["oauth_state"] == s2  # last write wins

    def test_subclass_can_override_session_key(self, bound_session):
        from autonomous.auth.github import GithubAuth

        class IsolatedAuth(GithubAuth):
            state_session_key = "github_oauth_state"

        auth = IsolatedAuth()
        _, state = auth.authenticate()
        assert bound_session["github_oauth_state"] == state
        assert "oauth_state" not in bound_session


class TestHandleResponseValidatesState:
    def test_missing_session_state_raises_csrf(self, bound_session):
        """No prior authenticate() means no stored state — must reject."""
        from authlib.integrations.base_client.errors import MismatchingStateError

        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        with pytest.raises(MismatchingStateError):
            auth.handle_response("http://cb/?code=x&state=anything")

    def test_uses_session_state_when_caller_omits_it(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        _, issued_state = auth.authenticate()
        assert bound_session["oauth_state"] == issued_state

        # Patch out the actual token exchange + userinfo HTTP calls.
        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ) as mock_fetch, patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value={"email": "a@b.c"})),
        ):
            userinfo, token = auth.handle_response(
                f"http://cb/?code=abc&state={issued_state}"
            )

        # Library passed the session-stored state, not None.
        assert mock_fetch.call_args.kwargs["state"] == issued_state
        assert token == {"access_token": "tok"}
        assert userinfo == {"email": "a@b.c"}

    def test_explicit_state_overrides_session(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        auth.authenticate()  # stores something in session
        bound_session["oauth_state"] = "session-value"

        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ) as mock_fetch, patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value={})),
        ):
            auth.handle_response(
                "http://cb/?code=abc&state=explicit-value", state="explicit-value"
            )

        assert mock_fetch.call_args.kwargs["state"] == "explicit-value"

    def test_state_cleared_after_success(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        _, issued_state = auth.authenticate()
        assert "oauth_state" in bound_session

        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ), patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value={})),
        ):
            auth.handle_response(f"http://cb/?code=abc&state={issued_state}")

        assert "oauth_state" not in bound_session

    def test_state_cleared_after_failure(self, bound_session):
        """A bad exchange must still burn the stored state (replay defense)."""
        from authlib.integrations.base_client.errors import MismatchingStateError

        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        _, issued_state = auth.authenticate()

        with patch.object(
            auth.session,
            "fetch_token",
            side_effect=MismatchingStateError("bad state"),
        ):
            with pytest.raises(MismatchingStateError):
                auth.handle_response(
                    f"http://cb/?code=abc&state={issued_state}"
                )

        assert "oauth_state" not in bound_session


class TestEndToEndFlow:
    """The audit's item 19 asks for an end-to-end OAuth test. This covers:
    authenticate -> store state -> callback -> validate -> exchange -> userinfo.
    """

    def test_happy_path(self, bound_session):
        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        uri, issued_state = auth.authenticate()

        # Caller redirects user to `uri`; user comes back with the same state
        # in the query string. Authlib internally compares URL state to the
        # state we pass in, so we mock it to assert the wiring works.
        callback_url = f"http://cb/?code=auth-code&state={issued_state}"

        fake_userinfo = {"email": "alice@example.com", "name": "Alice"}
        with patch.object(
            auth.session,
            "fetch_token",
            return_value={"access_token": "abc", "token_type": "bearer"},
        ) as mock_fetch, patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(
                json=MagicMock(return_value=fake_userinfo)
            ),
        ):
            userinfo, token = auth.handle_response(callback_url)

        # State was passed through to authlib (the library will compare it
        # against what's parsed out of the URL).
        assert mock_fetch.call_args.kwargs["state"] == issued_state
        assert userinfo == fake_userinfo
        assert token["access_token"] == "abc"
        # Replay defense: state is gone after success.
        assert "oauth_state" not in bound_session

    def test_csrf_attack_rejected(self, bound_session):
        """Attacker-crafted callback with no prior session state is rejected."""
        from authlib.integrations.base_client.errors import MismatchingStateError

        from autonomous.auth.github import GithubAuth

        auth = GithubAuth()
        # Note: no authenticate() call — attacker is sending the user
        # straight to the callback with their own code.
        with pytest.raises(MismatchingStateError):
            auth.handle_response("http://cb/?code=attacker-code&state=fake")
