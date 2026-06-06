"""Independent coverage for PR #41 / issue #40 — OAuth ``(provider, sub)``
stable identity on ``AutoUser``.

Email is mutable at the provider — a user changes their primary email, or
switches between provider-side aliases, and the legacy email-keyed lookup
in ``AutoUser.authenticate`` creates a duplicate record. The OIDC ``sub``
claim (or its provider-specific equivalent — Google's ``id`` on
``oauth2/v2/userinfo``, GitHub's numeric ``id`` on ``/user``) is the
stable identity; PR #41 adds ``oauth_provider`` + ``oauth_sub`` fields to
``AutoUser`` and threads them through ``AutoAuth.handle_response`` and
``AutoUser.authenticate`` so lookups prefer the stable pair, falling back
to email only for legacy unmigrated records.

Contracts pinned here:

1. **Schema:** ``AutoUser`` declares both ``oauth_provider`` and
   ``oauth_sub`` as ``StringAttr`` — they're persisted, optional, and
   participate in find().
2. **Lookup priority** in ``authenticate``: (provider, sub) first when
   both are present in ``user_info``, then email-fallback when (a) the
   pair didn't match AND (b) email is set.
3. **Backfill on email-match** — but ONLY when the matched record has
   no existing (provider, sub). A multi-provider user (Google then
   GitHub on the same email) must NOT have their original pair
   overwritten by the second provider's login.
4. **Type coercion of ``oauth_sub``** — int subs (GitHub's numeric
   ``id``) coerced to str so they match the StringAttr-stored value on
   subsequent logins.
5. **Legacy compat:** plain ``{"name", "email"}`` user_info dicts (the
   pre-#40 shape) still work — the (provider, sub) branch is skipped
   when both keys are absent.
6. **Missing-email tolerance** — GitHub users with private email + no
   ``user:email`` scope arrive with ``email=None``; the function must
   not crash AND must not overwrite stored email with empty.
7. **Per-provider subject extraction:** ``GoogleAuth._extract_sub`` reads
   ``sub or id``; ``GithubAuth._extract_sub`` reads ``id``; base
   ``AutoAuth._extract_sub`` reads ``sub``. Subclasses encode the
   per-provider userinfo shape.
8. **handle_response injection** is **both-or-neither** — the base
   ``AutoAuth`` (no ``provider_name``) must NOT inject an orphan
   ``oauth_sub``; injection only fires when the subclass declares a
   provider name AND ``_extract_sub`` returns a non-None subject.
9. **Caller-provided values win** — if the upstream userinfo already
   carries ``oauth_sub`` (custom provider shape) the injection must not
   overwrite it. If it carries ``oauth_sub`` but no ``oauth_provider``,
   the provider name is stamped without touching the sub.
10. **Round-trip safety for non-dict responses** — a list or scalar
    from ``.json()`` returns unchanged so error paths surface
    naturally rather than crashing in the injection step.
11. **Fixture isolation** — the dict that ``.json()`` returns is NOT
    mutated in place; ``handle_response`` copies before stamping so
    shared test fixtures (the ``MagicMock(json=MagicMock(return_value=
    fake))`` pattern) don't grow keys between calls.

Fresh-perspective check: I deliberately did NOT consult dev's local tests
under ``tests/_dev_local/`` (gitignored — invisible in the PR diff).
Tests derived from the diff in ``src/autonomous/auth/{autoauth,user,
github,google}.py``.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.auth.autoauth import AutoAuth
from autonomous.auth.github import GithubAuth
from autonomous.auth.google import GoogleAuth
from autonomous.auth.user import AutoUser


# ---------------------------------------------------------------------------
# Env scaffolding — these are read by GithubAuth/GoogleAuth __init__.
# Copied from tests/unit/test_unit_oauth_state.py so the file is
# self-contained / revertable in one rm.
# ---------------------------------------------------------------------------

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
        "GITHUB_AUTH_AUTHORIZE_URL",
        "https://github.example/login/oauth/authorize",
    )
    monkeypatch.setenv(
        "GITHUB_AUTH_TOKEN_URL",
        "https://github.example/login/oauth/access_token",
    )


@pytest.fixture
def bound_session():
    from autonomous.web import ContextSession, bind_session, clear_session

    store = ContextSession()
    token = bind_session(store)
    yield store
    clear_session(token)


# ===========================================================================
# Part 1 — Schema: AutoUser declares oauth_provider + oauth_sub
# ===========================================================================

class TestSchema:
    """Pin the field declarations on AutoUser. Without these, the
    StringAttr descriptor protocol fails on read/write and the
    authenticate() flow blows up at line 1 of the diff."""

    def test_oauth_provider_field_declared(self):
        # The StringAttr descriptor lives on the class; the resolved
        # MongoEngine ``_fields`` mapping is what queries actually use.
        assert "oauth_provider" in AutoUser._fields, (
            "AutoUser must declare oauth_provider as a StringAttr per #40 — "
            "missing means find(oauth_provider=...) silently misses the "
            "field-filter step and falls through to a collection scan"
        )

    def test_oauth_sub_field_declared(self):
        assert "oauth_sub" in AutoUser._fields, (
            "AutoUser must declare oauth_sub as a StringAttr per #40"
        )

    def test_fields_are_string_typed(self):
        """Both fields are StringAttr (not int, not list). The sub
        coercion in authenticate (str(oauth_sub)) is what bridges
        int-typed callers (raw GitHub /user ``id``) to the stored
        string value. If a future edit changes the field type the
        coercion contract breaks."""
        from autonomous.db.fields import StringField
        assert isinstance(AutoUser._fields["oauth_provider"], StringField)
        assert isinstance(AutoUser._fields["oauth_sub"], StringField)


# ===========================================================================
# Part 2 — AutoAuth base + subclass provider_name + _extract_sub
# ===========================================================================

class TestProviderNameClassAttr:
    """Base ``AutoAuth.provider_name`` must default to empty string so
    callers that pass raw user_info dicts (no OAuth subclass machinery)
    keep working — empty provider_name disables the injection branch in
    handle_response, preserving pre-#40 round-trip semantics for the
    base class."""

    def test_base_autoauth_provider_name_empty(self):
        assert AutoAuth.provider_name == ""

    def test_github_provider_name_is_github(self):
        # The persisted value on oauth_provider becomes the lookup key,
        # so it must be stable. "github" matches the docstring and the
        # storyteller integration.
        assert GithubAuth.provider_name == "github"

    def test_google_provider_name_is_google(self):
        assert GoogleAuth.provider_name == "google"


class TestExtractSubBase:
    """Base ``_extract_sub`` reads ``sub`` — the OIDC standard claim.
    Subclasses override only when the provider's userinfo endpoint
    deviates from that shape."""

    def test_base_reads_sub_key(self):
        auth = AutoAuth.__new__(AutoAuth)
        assert auth._extract_sub({"sub": "abc-123"}) == "abc-123"

    def test_base_returns_none_when_sub_missing(self):
        """Returning None must leave oauth_sub unset on the user. The
        authenticate flow then falls back to email lookup, which is the
        preserved legacy path for providers/responses that don't surface
        a sub."""
        auth = AutoAuth.__new__(AutoAuth)
        assert auth._extract_sub({"email": "a@b.c"}) is None

    def test_base_robust_to_extra_keys(self):
        auth = AutoAuth.__new__(AutoAuth)
        assert auth._extract_sub(
            {"sub": "x", "email": "a@b.c", "extra": object()}
        ) == "x"


class TestExtractSubGithub:
    """GitHub's ``/user`` endpoint returns a numeric ``id`` — the
    canonical GitHub user ID, stable across username changes. GitHub
    does NOT emit a ``sub`` claim on this endpoint, so the base
    implementation would always return None and the (provider, sub)
    path would never fire for GitHub users. The subclass override is
    what makes GitHub lookups stable."""

    def test_reads_id_key(self):
        auth = GithubAuth()
        assert auth._extract_sub({"id": 99887766, "login": "alice"}) == 99887766

    def test_returns_none_when_id_absent(self):
        auth = GithubAuth()
        assert auth._extract_sub({"login": "alice"}) is None

    def test_does_not_fall_back_to_sub(self):
        """GitHub never emits sub; if the userinfo dict has both (test
        fixture mistake), the GitHub override picks ``id`` so the stored
        oauth_sub matches the production /user response shape. If the
        override accidentally read sub, two test fixtures with different
        sub values for the same id would create distinct users."""
        auth = GithubAuth()
        assert auth._extract_sub(
            {"id": 12345, "sub": "should-not-be-used"}
        ) == 12345


class TestExtractSubGoogle:
    """``GoogleAuth.req_uri`` points at ``oauth2/v2/userinfo`` which
    returns the stable subject under ``id``. The override reads
    ``sub or id`` so a future swap to the OIDC userinfo endpoint
    (which DOES return ``sub``) doesn't silently change the
    (provider, sub) identity for existing users.

    Uses ``__new__`` to bypass ``GoogleAuth.__init__``'s discovery-URL
    fetch — the test environment doesn't have network access to
    ``GOOGLE_DISCOVERY_URL`` and the fetch is unrelated to the
    ``_extract_sub`` contract under test."""

    def _auth(self):
        return GoogleAuth.__new__(GoogleAuth)

    def test_reads_sub_when_present(self):
        assert self._auth()._extract_sub(
            {"sub": "oidc-sub", "id": "v2-id"}
        ) == "oidc-sub"

    def test_falls_back_to_id_when_sub_missing(self):
        # The current production case — oauth2/v2/userinfo returns id.
        assert self._auth()._extract_sub({"id": "v2-id"}) == "v2-id"

    def test_returns_none_when_both_missing(self):
        assert self._auth()._extract_sub({"email": "a@b.c"}) is None

    def test_empty_sub_falls_back_to_id(self):
        """A provider returning ``sub=""`` (some legacy responses) must
        fall back to id — the ``or`` short-circuits on falsy. Otherwise
        the stored oauth_sub would be empty-string and lookups would
        miss every record."""
        assert self._auth()._extract_sub(
            {"sub": "", "id": "fallback"}
        ) == "fallback"


# ===========================================================================
# Part 3 — AutoAuth.handle_response injects (provider, sub) into userinfo
# ===========================================================================

class _TestSubAuth(AutoAuth):
    """Minimal AutoAuth subclass with provider_name set, for exercising
    the handle_response injection branch without depending on Google/
    GitHub's __init__ env-var coupling."""
    provider_name = "test-provider"

    def __init__(self):
        # Skip the parent __init__ — it expects Authlib client config
        # that's irrelevant to handle_response's post-token logic.
        self.req_uri = "https://provider.test/userinfo"
        self.state_session_key = "oauth_state"
        self.session = MagicMock()

    def _extract_sub(self, raw_userinfo):
        return raw_userinfo.get("sub")


def _patch_session_token_exchange(auth):
    """Stub fetch_token so handle_response can proceed past the state-
    validation step without a real token exchange. Returns the patcher
    context manager pair (fetch_token, oauth_state mocked in session)."""
    auth.session.fetch_token = MagicMock(return_value={"access_token": "tok"})


class TestHandleResponseInjectsPair:
    """When the subclass has provider_name set AND ``_extract_sub``
    returns a subject, ``handle_response`` returns userinfo with both
    fields populated."""

    def test_injects_both_fields(self, bound_session):
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        fake_userinfo = {"sub": "abc-123", "email": "a@b.c", "name": "Alice"}
        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=fake_userinfo)),
        ):
            userinfo, token = auth.handle_response(
                "http://cb/?code=x&state=s"
            )
        assert userinfo["oauth_provider"] == "test-provider"
        assert userinfo["oauth_sub"] == "abc-123"
        # Original keys preserved.
        assert userinfo["email"] == "a@b.c"
        assert userinfo["name"] == "Alice"

    def test_sub_str_coerced(self, bound_session):
        """A numeric subject (e.g. GitHub's int id) must be coerced to
        str before injection so the stored value type-matches the
        StringAttr field."""
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        fake_userinfo = {"sub": 99887766, "email": "a@b.c"}
        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=fake_userinfo)),
        ):
            userinfo, _ = auth.handle_response("http://cb/?code=x&state=s")
        assert userinfo["oauth_sub"] == "99887766"
        assert isinstance(userinfo["oauth_sub"], str)


class TestHandleResponseBaseAutoAuthDoesNotInject:
    """Base ``AutoAuth`` has provider_name="" → injection is gated
    off → returns the raw response unchanged. This preserves pre-#40
    round-trip semantics for callers that subclass AutoAuth without
    setting provider_name."""

    def test_base_class_does_not_inject_orphan_sub(self, bound_session):
        bound_session["oauth_state"] = "s"

        class _UnnamedAuth(AutoAuth):
            # No provider_name override → defaults to "" → gated off.
            def __init__(self):
                self.req_uri = "https://x.test/u"
                self.state_session_key = "oauth_state"
                self.session = MagicMock()

        auth = _UnnamedAuth()
        _patch_session_token_exchange(auth)

        fake_userinfo = {"sub": "abc-123", "email": "a@b.c"}
        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=fake_userinfo)),
        ):
            userinfo, _ = auth.handle_response("http://cb/?code=x&state=s")

        # NO oauth_provider / oauth_sub keys — without a provider name to
        # pair with, an orphan oauth_sub would create ambiguity in the
        # multi-provider lookup branch downstream.
        assert "oauth_provider" not in userinfo
        assert "oauth_sub" not in userinfo


class TestHandleResponseNonDictRoundTrip:
    """``.json()`` might return a list or scalar on a malformed upstream
    response. The injection step must not crash — return the raw value
    unchanged so the error surfaces naturally at the caller."""

    @pytest.mark.parametrize("malformed", [
        ["a", "b"], "string-response", 42, None,
    ])
    def test_non_dict_returns_unchanged(self, bound_session, malformed):
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=malformed)),
        ):
            userinfo, _ = auth.handle_response("http://cb/?code=x&state=s")
        assert userinfo == malformed


class TestHandleResponseCallerWins:
    """If the caller pre-populated either key, the injection must not
    overwrite. Use case: a custom subclass that knows its provider's
    sub shape better than ``_extract_sub`` and pre-injects."""

    def test_caller_sub_not_overwritten(self, bound_session):
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        # Caller pre-populated oauth_sub; _extract_sub would extract a
        # different value from `sub` — pin that we keep the caller's.
        pre = {"sub": "from-extract", "oauth_sub": "caller-supplied",
               "email": "a@b.c"}
        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=pre)),
        ):
            userinfo, _ = auth.handle_response("http://cb/?code=x&state=s")
        assert userinfo["oauth_sub"] == "caller-supplied"
        # provider_name is stamped to complete the pair.
        assert userinfo["oauth_provider"] == "test-provider"

    def test_caller_provider_not_overwritten(self, bound_session):
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        pre = {"sub": "x", "oauth_provider": "caller-provider",
               "email": "a@b.c"}
        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=pre)),
        ):
            userinfo, _ = auth.handle_response("http://cb/?code=x&state=s")
        assert userinfo["oauth_provider"] == "caller-provider"
        assert userinfo["oauth_sub"] == "x"  # auto-stamped via _extract_sub


class TestHandleResponseDoesNotMutateFixture:
    """The dict returned by ``.json()`` is copied before injection. A
    shared fixture dict (the ``MagicMock(json=MagicMock(
    return_value=fake))`` pattern) must not grow oauth_provider/
    oauth_sub keys between calls."""

    def test_original_dict_unchanged(self, bound_session):
        bound_session["oauth_state"] = "s"
        auth = _TestSubAuth()
        _patch_session_token_exchange(auth)

        shared_fixture = {"sub": "abc-123", "email": "a@b.c"}
        snapshot = dict(shared_fixture)

        with patch(
            "autonomous.auth.autoauth.requests.get",
            return_value=MagicMock(
                json=MagicMock(return_value=shared_fixture)
            ),
        ):
            auth.handle_response("http://cb/?code=x&state=s")

        # The fixture dict has its original shape — no new keys.
        assert shared_fixture == snapshot, (
            f"handle_response must copy before stamping; "
            f"fixture mutated to: {shared_fixture}"
        )


# ===========================================================================
# Part 4 — AutoUser.authenticate lookup priority + backfill
# ===========================================================================

class _UserStub:
    """Minimal stub used as the ``cls`` argument to
    ``AutoUser.authenticate.__func__``. Stages a ``find`` table keyed
    by frozenset of query kwargs and tracks all calls.

    Constructor accepts any kwargs and stores them as attributes.
    save() is a no-op so the unit test doesn't touch Mongo."""

    # Populated per-test via classmethod calls.
    find_returns = None  # callable: kw_dict -> user or None
    find_calls = None    # list of kw_dicts

    def __init__(self, **kw):
        self.oauth_provider = kw.get("oauth_provider")
        self.oauth_sub = kw.get("oauth_sub")
        self.email = kw.get("email")
        self.name = kw.get("name", "")
        self.last_login = None
        self.state = "unauthenticated"
        self.role = "guest"
        self.saved = False

    @classmethod
    def find(cls, **kw):
        cls.find_calls.append(kw)
        return cls.find_returns(kw)

    def save(self):
        self.saved = True


def _fresh_stub(returns):
    """Create a fresh _UserStub subclass per test so find_calls/
    find_returns don't bleed between tests."""

    class _Per(_UserStub):
        pass

    _Per.find_calls = []
    _Per.find_returns = returns
    return _Per


def _authenticate(stub_cls, user_info, token=None):
    """Invoke the classmethod with a stub `cls`. Same pattern as the
    existing guest-cache tests use: ``AutoUser.method.__func__(stub)``."""
    return AutoUser.authenticate.__func__(stub_cls, user_info, token)


class TestAuthenticateLookupPriority:
    """(provider, sub) first; email-fallback only when the pair didn't
    match or is absent."""

    def test_pair_match_skips_email_lookup(self):
        existing = _UserStub()
        existing.oauth_provider = "google"
        existing.oauth_sub = "G123"
        existing.email = "old@example.com"

        # find by (google, G123) → existing; find by email → would be
        # a different user (but should never be queried).
        def _returns(kw):
            if kw == {"oauth_provider": "google", "oauth_sub": "G123"}:
                return existing
            raise AssertionError(
                f"email-fallback must not fire after pair match; "
                f"unexpected find call: {kw}"
            )

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G123",
                "email": "new@example.com",
                "name": "Alice",
            },
        )
        assert user is existing
        # Pair-only call — no email-fallback call recorded.
        assert stub.find_calls == [
            {"oauth_provider": "google", "oauth_sub": "G123"}
        ]

    def test_pair_miss_falls_back_to_email(self):
        existing = _UserStub()
        existing.email = "alice@example.com"
        existing.oauth_provider = None

        def _returns(kw):
            if "oauth_provider" in kw:
                return None  # pair miss
            if kw == {"email": "alice@example.com"}:
                return existing
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G123",
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        assert user is existing
        # Both lookups attempted in order.
        assert stub.find_calls[0] == {
            "oauth_provider": "google", "oauth_sub": "G123"
        }
        assert stub.find_calls[1] == {"email": "alice@example.com"}

    def test_no_match_creates_new_user(self):
        def _returns(kw):
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G123",
                "email": "new@example.com",
                "name": "Alice",
            },
        )
        assert isinstance(user, stub)
        # New user constructed with name + email.
        assert user.email == "new@example.com"
        assert user.name == "Alice"
        # Backfill stamped the pair on the new user.
        assert user.oauth_provider == "google"
        assert user.oauth_sub == "G123"
        assert user.saved is True

    def test_legacy_user_info_skips_pair_lookup(self):
        """Pre-#40 user_info shape ({name, email}) must skip the pair
        lookup entirely — no pair keys means email is the only signal."""
        existing = _UserStub()
        existing.email = "legacy@example.com"

        def _returns(kw):
            if kw == {"email": "legacy@example.com"}:
                return existing
            raise AssertionError(f"unexpected find call: {kw}")

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub, {"email": "legacy@example.com", "name": "Legacy"}
        )
        assert user is existing
        # No pair-lookup recorded.
        assert all(
            "oauth_provider" not in kw for kw in stub.find_calls
        )


class TestAuthenticateBackfill:
    """Backfill rules: matched-by-oauth (idempotent stamp), matched-by-
    email-with-no-provider (legacy upgrade), matched-by-email-with-
    different-provider (preserve original)."""

    def test_backfill_on_legacy_email_match(self):
        """User exists from pre-#40 (no oauth_provider). On next login
        with pair info, the pair is backfilled. Future logins will use
        the preferred pair-lookup path."""
        legacy_user = _UserStub()
        legacy_user.email = "alice@example.com"
        legacy_user.oauth_provider = None
        legacy_user.oauth_sub = None

        def _returns(kw):
            if kw == {"oauth_provider": "google", "oauth_sub": "G123"}:
                return None
            if kw == {"email": "alice@example.com"}:
                return legacy_user
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G123",
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        assert user is legacy_user
        assert user.oauth_provider == "google"
        assert user.oauth_sub == "G123"

    def test_no_overwrite_when_matched_by_email_has_different_provider(self):
        """Multi-provider scenario: user signed in via Google before, has
        oauth_provider='google' stored. They then sign in via GitHub with
        the same email — the email lookup finds the record, but the
        stored google-pair must NOT be overwritten by github's pair.
        Otherwise the next Google login would silently re-bind to the
        github pair, churning forever."""
        google_user = _UserStub()
        google_user.email = "alice@example.com"
        google_user.oauth_provider = "google"
        google_user.oauth_sub = "G123"

        def _returns(kw):
            # GitHub pair lookup → miss (this email has no github pair yet).
            if kw == {"oauth_provider": "github", "oauth_sub": "GH999"}:
                return None
            if kw == {"email": "alice@example.com"}:
                return google_user
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": "GH999",
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        assert user is google_user
        # Pair preserved — was google/G123 before, still google/G123 after.
        assert user.oauth_provider == "google"
        assert user.oauth_sub == "G123"

    def test_idempotent_stamp_on_pair_match(self):
        """When matched by pair, the backfill condition (matched_by_oauth
        is True) re-stamps the pair. Idempotent — no observable change,
        but pin behavior so a future refactor doesn't introduce a check
        that prevents the stamp (and breaks legacy users with a corrupt
        partial-stamp where oauth_provider is set but oauth_sub isn't)."""
        existing = _UserStub()
        existing.email = "alice@example.com"
        existing.oauth_provider = "google"
        existing.oauth_sub = "G123"

        def _returns(kw):
            if kw == {"oauth_provider": "google", "oauth_sub": "G123"}:
                return existing
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G123",
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        assert user.oauth_provider == "google"
        assert user.oauth_sub == "G123"


class TestAuthenticateSubCoercion:
    """``oauth_sub`` is coerced to str before lookup AND before storage.
    GitHub's /user returns numeric id; test fixtures mirror that. The
    StringAttr-stored value is str; without coercion the int lookup
    silently misses on the second login."""

    def test_int_sub_coerced_before_lookup(self):
        find_calls_kw = []

        def _returns(kw):
            find_calls_kw.append(kw)
            return None

        stub = _fresh_stub(_returns)
        _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": 99887766,  # int from raw GitHub /user
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        # Pair-lookup call uses str, not int.
        assert find_calls_kw[0] == {
            "oauth_provider": "github", "oauth_sub": "99887766"
        }, (
            f"pair lookup must coerce int sub to str so it matches the "
            f"StringAttr-stored value; got: {find_calls_kw[0]}"
        )

    def test_int_sub_stored_as_str_on_new_user(self):
        stub = _fresh_stub(lambda kw: None)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": 99887766,
                "email": "alice@example.com",
                "name": "Alice",
            },
        )
        assert user.oauth_sub == "99887766"
        assert isinstance(user.oauth_sub, str)


class TestAuthenticateMissingEmail:
    """GitHub users with private email + no ``user:email`` scope arrive
    with ``email=None``. Pre-#40 ``user_info['email'].strip()`` would
    raise AttributeError; #40's ``.get(...)`` + truthy-guard keeps the
    flow alive."""

    def test_missing_email_does_not_crash(self):
        """The (provider, sub) path runs even when email is absent."""
        new_user = None  # confirms a new user is created

        def _returns(kw):
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": "GH999",
                "name": "Alice",
                # no email key at all
            },
        )
        assert user.oauth_provider == "github"
        assert user.oauth_sub == "GH999"
        # email stays None on the new user — we did NOT pass email,
        # construction used cls(name=name, email=email=None).
        assert user.email is None

    def test_none_email_does_not_overwrite_stored(self):
        """If a user has a stored email and a subsequent login arrives
        with email=None (provider stripped it), the stored email must
        NOT be wiped — the ``if email:`` guard around ``user.email =
        email`` is what prevents the drop. Pin so a future refactor
        that drops the guard doesn't silently truncate user records."""
        existing = _UserStub()
        existing.email = "stable-stored@example.com"
        existing.oauth_provider = "github"
        existing.oauth_sub = "GH999"

        def _returns(kw):
            if kw == {"oauth_provider": "github", "oauth_sub": "GH999"}:
                return existing
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": "GH999",
                "name": "Alice",
                # no email — provider scope stripped it
            },
        )
        assert user.email == "stable-stored@example.com"

    def test_empty_email_does_not_crash_strip(self):
        """An empty-string email arriving from a provider must not crash
        the .strip() call; the truthy guard catches that case."""
        def _returns(kw):
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": "GH999",
                "email": "",
                "name": "Alice",
            },
        )
        # Construction goes through; email becomes None per the
        # `if raw_email else None` ternary on raw_email="".
        assert user.email is None

    def test_missing_name_does_not_crash(self):
        """Pre-#40 ``user_info['name'].strip()`` would KeyError without
        a name. Now ``.get('name') or ''`` keeps the flow alive."""
        def _returns(kw):
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                "oauth_sub": "GH999",
                "email": "a@b.c",
                # no name
            },
        )
        assert user.name == ""


class TestAuthenticatePairOnlyOnePieceSkipsPairLookup:
    """The pair-lookup gate is ``if oauth_provider and oauth_sub_str``.
    Only-one-piece must fall through to the email lookup so a half-
    populated dict (e.g. provider with no sub) doesn't error on a
    find() call with an empty filter."""

    def test_provider_without_sub_skips_pair_lookup(self):
        existing = _UserStub()
        existing.email = "a@b.c"

        def _returns(kw):
            if kw == {"email": "a@b.c"}:
                return existing
            raise AssertionError(
                f"unexpected pair-lookup with no sub: {kw}"
            )

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "github",
                # no oauth_sub
                "email": "a@b.c",
                "name": "Alice",
            },
        )
        assert user is existing

    def test_sub_without_provider_skips_pair_lookup(self):
        existing = _UserStub()
        existing.email = "a@b.c"

        def _returns(kw):
            if kw == {"email": "a@b.c"}:
                return existing
            raise AssertionError(
                f"unexpected pair-lookup with no provider: {kw}"
            )

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                # no oauth_provider
                "oauth_sub": "GH999",
                "email": "a@b.c",
                "name": "Alice",
            },
        )
        assert user is existing
