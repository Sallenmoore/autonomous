"""Independent coverage for PR #137 / issue #136 — elevated user.role
must survive ``AutoUser.authenticate()`` re-login.

Before #137, ``AutoUser.authenticate`` set ``user.role = "user"``
**unconditionally** on every OAuth login. Any role granted out-of-band
— an admin UI flipping ``role`` to ``"admin"``, a direct DB write
elevating a user to a custom role, etc. — was silently reset to
``"user"`` the next time that user signed in via OAuth. Practical
consequence: a persistent ``admin`` (or any non-default) role was
impossible for OAuth-authenticated users; consumers worked around
this by subclassing ``AutoUser`` and recapturing-and-restoring the
role around ``super().authenticate(...)``.

Contract pinned here:

1. **Guest → user promotion still fires.** A user record whose stored
   role is the schema default ``"guest"`` gets bumped to ``"user"`` on
   login. This is the legitimate "you just confirmed your account via
   OAuth so you're no longer the bootstrapped guest" path.
2. **Admin survives login.** A user with ``role="admin"`` retains
   that role after authenticate(). This is the headline fix.
3. **Any non-guest, non-default role survives login.** The guard is
   ``if user.role == "guest"`` — not ``if user.role in {"admin"}`` or
   any hardcoded role-set. A custom ``"moderator"`` (or any string a
   downstream consumer wants to use) must survive equally — the
   library deliberately leaves role-vocabulary to the consumer.
4. **Already-promoted ``"user"`` is idempotent.** A returning user
   whose stored role is ``"user"`` stays ``"user"`` — the role-write
   branch is skipped, so re-login does not thrash the ``role`` field.
5. **New-user signup still lands at ``"user"``.** A first-time OAuth
   sign-in (no existing record) constructs ``cls(name=..., email=...)``
   which inherits the schema default ``role="guest"`` (per
   ``AutoUser.role = StringAttr(default="guest")`` at user.py line 28),
   then the promotion branch fires in the same step — net effect: the
   saved user has ``role="user"``. This must NOT regress to a literal
   ``"guest"`` save.
6. **Admin survives across the OIDC (provider, sub) match path.**
   PR #41/#40 added stable identity lookup; the role-preservation guard
   applies to records matched via the (provider, sub) pair, not just
   via email. Pin this so a future refactor can't accidentally split
   role behavior between the two lookup paths.

Fresh-perspective check: I deliberately did NOT consult dev's local
tests under ``tests/_dev_local/`` (gitignored — invisible in the PR
diff). Tests derived from the diff in ``src/autonomous/auth/user.py``
and the surrounding ``authenticate()`` body read independently.

Stubbing pattern (``_UserStub`` + ``AutoUser.authenticate.__func__``)
is the same one used by
``tests/unit/test_unit_oauth_provider_sub_identity_iter_2026-06-06.py``
— pure-Python execution of the classmethod with a no-op ``find``/
``save`` so the unit tier does not require MongoDB.
"""

import pytest

from autonomous.auth.user import AutoUser


# ---------------------------------------------------------------------------
# Stub plumbing — minimal cls-substitute that exercises the
# ``authenticate`` classmethod without touching the ORM.
# ---------------------------------------------------------------------------

class _UserStub:
    """Stub used as ``cls`` for ``AutoUser.authenticate.__func__``.

    ``find_returns`` is a callable ``(kw_dict) -> user_or_None`` set per
    test. ``save()`` records the call so the test can assert that the
    role-preservation branch ran (or didn't) without a real Mongo write.
    Constructor mirrors ``AutoUser`` field initialization: role defaults
    to ``"guest"`` so a newly-constructed instance behaves the way the
    schema would.
    """

    find_returns = None  # callable: kw_dict -> user or None
    find_calls = None    # list of kw_dicts

    def __init__(self, **kw):
        self.oauth_provider = kw.get("oauth_provider")
        self.oauth_sub = kw.get("oauth_sub")
        self.email = kw.get("email")
        self.name = kw.get("name", "")
        self.last_login = None
        self.state = "unauthenticated"
        # Match the schema default — ``StringAttr(default="guest")`` on
        # AutoUser.role (user.py line 28). The unit must mirror this
        # because the promotion branch keys off ``"guest"`` exactly.
        self.role = kw.get("role", "guest")
        self.saved = False
        self.save_count = 0

    @classmethod
    def find(cls, **kw):
        cls.find_calls.append(kw)
        return cls.find_returns(kw)

    def save(self):
        self.saved = True
        self.save_count += 1


def _fresh_stub(returns):
    """Per-test stub subclass so ``find_calls``/``find_returns`` don't
    bleed across tests."""

    class _Per(_UserStub):
        pass

    _Per.find_calls = []
    _Per.find_returns = returns
    return _Per


def _authenticate(stub_cls, user_info, token=None):
    """Invoke ``AutoUser.authenticate`` against the stub `cls`. Mirrors
    the existing guest-cache / OIDC-identity test files."""
    return AutoUser.authenticate.__func__(stub_cls, user_info, token)


# ===========================================================================
# Part 1 — Guest → user promotion still fires (legitimate path).
# ===========================================================================

class TestGuestPromotion:
    """The fix narrows the role-write, it does not eliminate it. A
    ``"guest"`` role on a returning user must still get bumped to
    ``"user"`` — that's the original intent the unconditional write
    was overshooting."""

    def test_returning_guest_promoted_to_user(self):
        existing = _UserStub()
        existing.email = "guest-returnee@example.com"
        existing.role = "guest"  # explicit; matches schema default.

        def _returns(kw):
            return existing if kw == {"email": "guest-returnee@example.com"} else None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {"email": "guest-returnee@example.com", "name": "Returnee"},
        )
        assert user is existing
        assert user.role == "user", (
            "guest role MUST be promoted to user on login — this is "
            "the legitimate purpose of the role-write branch the #137 "
            "fix narrowed, NOT removed"
        )
        assert user.saved, "role write must accompany the save() call"


# ===========================================================================
# Part 2 — Admin survives login (the headline fix).
# ===========================================================================

class TestAdminPreservation:
    """The bug #136 was: an admin user re-authenticating via OAuth had
    their role silently downgraded to ``"user"`` because the assignment
    was unconditional. Pin admin-survives behavior so a future refactor
    can't accidentally regress."""

    def test_admin_role_survives_email_match_login(self):
        existing = _UserStub()
        existing.email = "admin@example.com"
        existing.role = "admin"

        def _returns(kw):
            return existing if kw == {"email": "admin@example.com"} else None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {"email": "admin@example.com", "name": "Admin"},
        )
        assert user is existing
        assert user.role == "admin", (
            "admin role MUST survive OAuth re-login — issue #136 fix. "
            "Unconditional ``user.role = 'user'`` here previously wiped "
            "the elevation."
        )
        # State transitions that SHOULD happen still happen.
        assert user.state == "authenticated"
        assert user.saved


# ===========================================================================
# Part 3 — Any non-guest role survives (no hardcoded role allowlist).
# ===========================================================================

class TestArbitraryRolePreservation:
    """The guard is ``if user.role == "guest"`` — single-default
    sentinel. Any other role string (consumer-defined vocabulary like
    ``"moderator"``, ``"editor"``, etc.) must equally survive, because
    the library deliberately does NOT impose a role-set. Pin this
    against an over-eager future refactor that checks
    ``user.role in {"guest", "user"}`` and accidentally re-downgrades
    custom roles back to ``"user"``."""

    @pytest.mark.parametrize(
        "custom_role",
        ["moderator", "editor", "superadmin", "billing", "readonly"],
    )
    def test_custom_role_survives_login(self, custom_role):
        existing = _UserStub()
        existing.email = "custom@example.com"
        existing.role = custom_role

        def _returns(kw):
            return existing if kw == {"email": "custom@example.com"} else None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {"email": "custom@example.com", "name": "Custom"},
        )
        assert user is existing
        assert user.role == custom_role, (
            f"role {custom_role!r} (consumer-defined) must survive — "
            "the guard is a single-value comparison against \"guest\", "
            "not an allowlist of known roles"
        )


# ===========================================================================
# Part 4 — Already-``"user"`` role is idempotent.
# ===========================================================================

class TestAlreadyUserIdempotent:
    """A returning user whose stored role is already ``"user"`` re-logs
    in: the role write branch must be skipped (guard is ``role ==
    "guest"``, not ``role != "user"``). Pin this so a future "always
    write to normalize the field" refactor doesn't get re-introduced —
    the whole point of the guard is to write LESS, not more."""

    def test_user_role_unchanged_on_relogin(self):
        existing = _UserStub()
        existing.email = "returning@example.com"
        existing.role = "user"

        def _returns(kw):
            return existing if kw == {"email": "returning@example.com"} else None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {"email": "returning@example.com", "name": "Returning"},
        )
        assert user is existing
        assert user.role == "user", (
            "``user`` role must remain ``user`` — no transition, no "
            "re-write. The guard's ``role == 'guest'`` check skips this "
            "branch entirely."
        )
        # save() is still called for last_login / state — but role
        # was not re-written within authenticate.
        assert user.saved


# ===========================================================================
# Part 5 — New-user signup lands at ``"user"`` (regression sanity).
# ===========================================================================

class TestNewUserStillLandsAtUser:
    """Critical regression-sanity guard: a first-time OAuth signin must
    NOT result in a stored ``role="guest"``. The flow is
    ``cls(name=..., email=...)`` (no role kwarg → schema default
    ``"guest"`` applies) followed by the promotion branch which then
    bumps that ``"guest"`` to ``"user"``. If the promotion branch were
    accidentally narrowed further (e.g. ``and user.pk is not None``)
    new users would persist at ``"guest"`` — silent regression. Pin it."""

    def test_first_time_signin_lands_at_user(self):
        def _returns(kw):
            return None  # no existing user — triggers new-user branch.

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {"email": "newcomer@example.com", "name": "Newcomer"},
        )
        # A brand-new stub instance was constructed; role started at
        # the schema default ("guest") and was promoted to ``"user"``
        # in the same authenticate() call.
        assert user.role == "user", (
            "new user signup must persist at ``user``, not ``guest`` — "
            "the promotion branch in authenticate() is what bridges the "
            "schema default to the post-login role. Regressing this "
            "would mean every brand-new OAuth signup lands at ``guest`` "
            "and is_guest stays True forever."
        )
        assert user.email == "newcomer@example.com"
        assert user.state == "authenticated"
        assert user.saved


# ===========================================================================
# Part 6 — Admin survives the OIDC (provider, sub) match path too.
# ===========================================================================

class TestAdminSurvivesOidcMatchPath:
    """PR #41/#40 added stable identity via ``oauth_provider`` +
    ``oauth_sub``. The role-preservation guard sits AFTER both lookup
    paths converge on a ``user`` variable, so it should apply equally
    whether the user was matched by the OIDC pair OR by email-fallback.
    Pin this explicitly so a future refactor that moves the role-write
    inside one of the branches can't accidentally split behavior
    between login paths."""

    def test_admin_via_oidc_pair_match(self):
        existing = _UserStub()
        existing.email = "admin@example.com"
        existing.oauth_provider = "google"
        existing.oauth_sub = "G-12345"
        existing.role = "admin"

        def _returns(kw):
            if kw == {"oauth_provider": "google", "oauth_sub": "G-12345"}:
                return existing
            return None

        stub = _fresh_stub(_returns)
        user = _authenticate(
            stub,
            {
                "oauth_provider": "google",
                "oauth_sub": "G-12345",
                "email": "admin@example.com",
                "name": "Admin",
            },
        )
        assert user is existing
        assert user.role == "admin", (
            "admin role MUST survive across the OIDC (provider, sub) "
            "match path — the role-preservation guard is unified for "
            "both lookup paths because it sits after both converge."
        )
        # Verify we actually went through the pair-match path
        # (not email-fallback) so the test name is honest.
        assert stub.find_calls[0] == {
            "oauth_provider": "google", "oauth_sub": "G-12345"
        }
