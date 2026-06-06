"""Independent coverage for PR #45 / issue #44 — three new OAuth providers:
``FacebookAuth``, ``DiscordAuth``, ``MicrosoftAuth``.

PR #45 is purely additive: three ``AutoAuth`` subclasses following the
**static-endpoint** idiom of ``GithubAuth`` (bake well-known endpoints as
defaults, read ``<PROVIDER>_AUTH_*`` env overrides, make NO network call at
construction — unlike ``GoogleAuth`` which fetches an OIDC discovery doc).
Each sets ``provider_name`` and overrides ``_extract_sub`` so the
``(oauth_provider, oauth_sub)`` stable-identity pair from #40 is injected by
``AutoAuth.handle_response`` automatically.

Contracts pinned here (derived from the diff in ``src/autonomous/auth/
{discord,facebook,microsoft,__init__}.py`` — the base ``handle_response``
injection logic is from #40/PR#41 and exercised here against the new
subclasses):

1. **Export surface** — all three are importable from ``autonomous.auth``.
2. **provider_name** is the correct short slug per subclass.
3. **No-network construction** — instantiating makes no HTTP call. Proven by
   patching ``requests.get``/``requests.post`` to explode and asserting
   construction still succeeds and they are never called.
4. **Baked default endpoints** — authorize/token/userinfo URLs default to the
   providers' well-known values when no env override is present.
5. **Default scopes** — Facebook ``["email","public_profile"]``, Discord
   ``["identify","email"]``, Microsoft ``["openid","email","profile"]``.
6. **Env overrides win** — ``<PROVIDER>_AUTH_{AUTHORIZE,TOKEN,USERINFO}_URL``
   and ``_SCOPE`` override the defaults.
7. **Scope CSV-split** — a comma-containing ``_SCOPE`` string is split into a
   list; a comma-less string is left as-is (matches the source guard
   ``if isinstance(scope, str) and "," in scope``).
8. **_extract_sub per provider** — Facebook/Discord read ``id``; Microsoft
   reads ``sub`` then falls back to ``oid``; an empty ``sub`` falls through to
   ``oid`` (the ``or`` short-circuit), and an all-missing payload yields
   ``None``.
9. **Microsoft tenant** — ``MICROSOFT_AUTH_TENANT`` is interpolated into the
   default authorize/token URLs; a full-URL env override still wins over the
   tenant-built default.
10. **handle_response injection end-to-end** — for each provider a realistic
    userinfo payload gets ``oauth_provider`` + stringified ``oauth_sub``
    stamped onto the returned dict (both-or-neither, sub coerced to str).

Fresh-perspective check: I did NOT consult dev's ``tests/_dev_local/``
(gitignored, invisible in the PR diff). Tests written from the diff alone.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.auth.discord import DiscordAuth
from autonomous.auth.facebook import FacebookAuth
from autonomous.auth.microsoft import MicrosoftAuth


# ---------------------------------------------------------------------------
# Minimal env so the *_CLIENT_ID etc. reads resolve to real strings rather
# than None. Endpoint/scope vars are intentionally left UNSET here so the
# default-baking branches are what most tests observe; tests that exercise
# overrides set their own vars via monkeypatch.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _provider_env(monkeypatch):
    for prov in ("FACEBOOK", "DISCORD", "MICROSOFT"):
        monkeypatch.setenv(f"{prov}_AUTH_CLIENT_ID", f"test-{prov.lower()}-id")
        monkeypatch.setenv(f"{prov}_AUTH_CLIENT_SECRET", f"test-{prov.lower()}-secret")
        monkeypatch.setenv(f"{prov}_AUTH_REDIRECT_URL", "http://localhost/cb")
        # Make sure no stray endpoint/scope/tenant overrides leak in from the
        # host environment — defaults must be observable.
        for suffix in ("AUTHORIZE_URL", "TOKEN_URL", "USERINFO_URL", "SCOPE"):
            monkeypatch.delenv(f"{prov}_AUTH_{suffix}", raising=False)
    monkeypatch.delenv("MICROSOFT_AUTH_TENANT", raising=False)


@pytest.fixture
def bound_session():
    from autonomous.web import ContextSession, bind_session, clear_session

    store = ContextSession()
    token = bind_session(store)
    yield store
    clear_session(token)


# Per-provider parameter table: (class, slug, sub-field key, sample sub).
PROVIDERS = [
    (FacebookAuth, "facebook", "id", "100008675309"),
    (DiscordAuth, "discord", "id", "80351110224678912"),
    (MicrosoftAuth, "microsoft", "sub", "AAAAAAAAAAAAAAAAAAAAAIm+abc"),
]


# ===========================================================================
# Part 1 — Export surface + provider_name
# ===========================================================================

class TestExportSurface:
    def test_all_three_importable_from_package_root(self):
        from autonomous.auth import (  # noqa: F401
            DiscordAuth as D,
            FacebookAuth as F,
            MicrosoftAuth as M,
        )

        assert (F, D, M) == (FacebookAuth, DiscordAuth, MicrosoftAuth)

    @pytest.mark.parametrize("cls,slug", [(c, s) for c, s, _, _ in PROVIDERS])
    def test_provider_name_slug(self, cls, slug):
        # Both class-level and instance-level — provider_name gates the
        # (oauth_provider, oauth_sub) injection in handle_response.
        assert cls.provider_name == slug
        assert cls().provider_name == slug


# ===========================================================================
# Part 2 — No-network construction (static-endpoint idiom)
# ===========================================================================

class TestNoNetworkAtConstruction:
    """GoogleAuth fetches a discovery doc at __init__; these three must NOT.
    Patch the HTTP layer to explode and confirm construction still works."""

    @pytest.mark.parametrize("cls", [c for c, _, _, _ in PROVIDERS])
    def test_construction_makes_no_http_call(self, cls):
        boom = MagicMock(side_effect=AssertionError("network at construction!"))
        with patch("autonomous.auth.autoauth.requests.get", boom), patch(
            "requests.get", boom
        ), patch("requests.post", boom):
            inst = cls()  # must not raise
        boom.assert_not_called()
        # And the baked endpoints are populated (no None issuer/token).
        assert inst.issuer
        assert inst.token_endpoint
        assert inst.req_uri


# ===========================================================================
# Part 3 — Baked default endpoints + scopes
# ===========================================================================

class TestDefaultEndpoints:
    def test_facebook_defaults(self):
        a = FacebookAuth()
        assert a.issuer == "https://www.facebook.com/v19.0/dialog/oauth"
        assert a.token_endpoint == "https://graph.facebook.com/v19.0/oauth/access_token"
        assert a.req_uri == "https://graph.facebook.com/me?fields=id,name,email,picture"
        assert a.scope == ["email", "public_profile"]

    def test_discord_defaults(self):
        a = DiscordAuth()
        assert a.issuer == "https://discord.com/oauth2/authorize"
        assert a.token_endpoint == "https://discord.com/api/oauth2/token"
        assert a.req_uri == "https://discord.com/api/users/@me"
        assert a.scope == ["identify", "email"]

    def test_microsoft_defaults_use_common_tenant(self):
        a = MicrosoftAuth()
        assert a.issuer == (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        )
        assert a.token_endpoint == (
            "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        )
        assert a.req_uri == "https://graph.microsoft.com/oidc/userinfo"
        assert a.scope == ["openid", "email", "profile"]


# ===========================================================================
# Part 4 — Env overrides + scope CSV-split
# ===========================================================================

class TestEnvOverrides:
    def test_endpoint_overrides_win(self, monkeypatch):
        monkeypatch.setenv("DISCORD_AUTH_AUTHORIZE_URL", "https://x.test/authz")
        monkeypatch.setenv("DISCORD_AUTH_TOKEN_URL", "https://x.test/token")
        monkeypatch.setenv("DISCORD_AUTH_USERINFO_URL", "https://x.test/me")
        a = DiscordAuth()
        assert a.issuer == "https://x.test/authz"
        assert a.token_endpoint == "https://x.test/token"
        assert a.req_uri == "https://x.test/me"

    def test_scope_csv_is_split_into_list(self, monkeypatch):
        monkeypatch.setenv("FACEBOOK_AUTH_SCOPE", "email,public_profile,user_friends")
        a = FacebookAuth()
        assert a.scope == ["email", "public_profile", "user_friends"]

    def test_scope_single_value_left_as_string(self, monkeypatch):
        # No comma → the `isinstance(str) and "," in scope` guard is False,
        # so the raw string is passed through unchanged.
        monkeypatch.setenv("MICROSOFT_AUTH_SCOPE", "openid")
        a = MicrosoftAuth()
        assert a.scope == "openid"


# ===========================================================================
# Part 5 — Microsoft tenant interpolation
# ===========================================================================

class TestMicrosoftTenant:
    def test_tenant_env_interpolated_into_default_urls(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_AUTH_TENANT", "contoso.onmicrosoft.com")
        a = MicrosoftAuth()
        assert a.issuer == (
            "https://login.microsoftonline.com/"
            "contoso.onmicrosoft.com/oauth2/v2.0/authorize"
        )
        assert a.token_endpoint == (
            "https://login.microsoftonline.com/"
            "contoso.onmicrosoft.com/oauth2/v2.0/token"
        )

    def test_full_url_override_beats_tenant_default(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_AUTH_TENANT", "contoso.onmicrosoft.com")
        monkeypatch.setenv(
            "MICROSOFT_AUTH_AUTHORIZE_URL", "https://single-tenant.test/authz"
        )
        a = MicrosoftAuth()
        # Explicit full-URL override wins; tenant only shapes the *default*.
        assert a.issuer == "https://single-tenant.test/authz"
        # Token URL was not overridden, so it still uses the tenant default.
        assert "contoso.onmicrosoft.com" in a.token_endpoint


# ===========================================================================
# Part 6 — _extract_sub per provider
# ===========================================================================

class TestExtractSub:
    def test_facebook_reads_id(self):
        assert FacebookAuth()._extract_sub({"id": "fb-123", "email": "a@b.c"}) == "fb-123"

    def test_facebook_missing_id_is_none(self):
        assert FacebookAuth()._extract_sub({"email": "a@b.c"}) is None

    def test_discord_reads_id(self):
        assert DiscordAuth()._extract_sub({"id": "dc-999", "username": "x"}) == "dc-999"

    def test_microsoft_prefers_sub(self):
        a = MicrosoftAuth()
        assert a._extract_sub({"sub": "ms-sub", "oid": "ms-oid"}) == "ms-sub"

    def test_microsoft_falls_back_to_oid_when_sub_absent(self):
        a = MicrosoftAuth()
        assert a._extract_sub({"oid": "ms-oid"}) == "ms-oid"

    def test_microsoft_empty_sub_falls_through_to_oid(self):
        # `"" or oid` short-circuits to oid — empty string is falsy.
        a = MicrosoftAuth()
        assert a._extract_sub({"sub": "", "oid": "ms-oid"}) == "ms-oid"

    def test_microsoft_all_missing_is_none(self):
        a = MicrosoftAuth()
        assert a._extract_sub({"email": "a@b.c"}) is None


# ===========================================================================
# Part 7 — handle_response injects (oauth_provider, oauth_sub) end-to-end
# ===========================================================================

class TestHandleResponseInjection:
    """Drive the full authenticate() -> handle_response() path with the token
    exchange + userinfo GET mocked. The new subclasses must produce the
    stable-identity pair because each sets provider_name + _extract_sub."""

    @pytest.mark.parametrize("cls,slug,key,sample", PROVIDERS)
    def test_pair_injected(self, cls, slug, key, sample, bound_session):
        auth = cls()
        _, issued_state = auth.authenticate()  # builds authz URL, stores state
        callback = f"http://localhost/cb?code=abc&state={issued_state}"

        fake_userinfo = {key: sample, "email": "user@example.com"}
        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ), patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=dict(fake_userinfo))),
        ):
            data, token = auth.handle_response(callback)

        assert data["oauth_provider"] == slug
        assert data["oauth_sub"] == str(sample)
        assert data["email"] == "user@example.com"
        assert token == {"access_token": "tok"}

    def test_numeric_sub_is_stringified(self, bound_session):
        # Discord/Facebook ids arrive as ints from some JSON decoders; the
        # base injection coerces to str so subsequent StringAttr lookups match.
        auth = DiscordAuth()
        _, issued_state = auth.authenticate()
        callback = f"http://localhost/cb?code=abc&state={issued_state}"
        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ), patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(
                json=MagicMock(return_value={"id": 80351110224678912})
            ),
        ):
            data, _ = auth.handle_response(callback)
        assert data["oauth_sub"] == "80351110224678912"
        assert isinstance(data["oauth_sub"], str)

    def test_no_sub_means_no_pair_injected(self, bound_session):
        # Microsoft userinfo with neither sub nor oid → _extract_sub returns
        # None → both-or-neither contract leaves the dict pair-free.
        auth = MicrosoftAuth()
        _, issued_state = auth.authenticate()
        callback = f"http://localhost/cb?code=abc&state={issued_state}"
        with patch.object(
            auth.session, "fetch_token", return_value={"access_token": "tok"}
        ), patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(
                json=MagicMock(return_value={"email": "user@example.com"})
            ),
        ):
            data, _ = auth.handle_response(callback)
        assert "oauth_sub" not in data
        assert "oauth_provider" not in data
