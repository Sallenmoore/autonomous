"""Item 8: skip redundant Mongo + session writes in auth_required.

The decorator used to call ``user.save()`` and rewrite ``session["user"]``
on every authenticated request. For an authenticated request that doesn't
change anything that meant a Mongo write per pageview.

The new contract:

- ``last_login`` is throttled to one DB write per
  ``cls.last_login_throttle_seconds`` (default 60s).
- The session blob is rewritten only if the user JSON changed.
- Setting ``last_login_throttle_seconds = 0`` restores the legacy
  every-request behaviour.
"""

from datetime import datetime, timedelta

import pytest


class _CountingUser:
    """In-memory User stand-in that tracks save() / to_json() calls."""

    def __init__(
        self,
        pk: int = 1,
        state: str = "authenticated",
        is_guest: bool = False,
        is_admin: bool = False,
        last_login: datetime | None = None,
        json_payload: str = '{"pk": 1, "v": 1}',
    ):
        self.pk = pk
        self.state = state
        self._is_guest = is_guest
        self._is_admin = is_admin
        self.last_login = last_login
        self._json = json_payload
        self.save_calls = 0

    @property
    def is_guest(self) -> bool:
        return self._is_guest

    @property
    def is_admin(self) -> bool:
        return self._is_admin

    def save(self):
        self.save_calls += 1
        return self.pk

    def to_json(self) -> str:
        return self._json


class _UserClass:
    current: _CountingUser | None = None
    guest = _CountingUser(pk=0, state="guest", is_guest=True)

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

    original_user = AutoAuth.user_class
    original_throttle = AutoAuth.last_login_throttle_seconds
    AutoAuth.user_class = _UserClass
    yield AutoAuth
    AutoAuth.user_class = original_user
    AutoAuth.last_login_throttle_seconds = original_throttle
    _UserClass.current = None


@pytest.fixture
def session():
    from autonomous.web import ContextSession, bind_session, clear_session

    # Pre-populate with a sentinel so AutoAuth.current_user() takes the
    # ``from_json`` branch (and returns the test's _CountingUser) rather
    # than falling through to the guest user.
    store = ContextSession({"user": "{}"})
    token = bind_session(store)
    yield store
    clear_session(token)


class TestLastLoginThrottle:
    def test_first_request_saves(self, auth_cls, session):
        user = _CountingUser(last_login=None)
        _UserClass.current = user

        @auth_cls.auth_required()
        def view():
            return "ok"

        view()
        assert user.save_calls == 1

    def test_recent_login_skips_save(self, auth_cls, session):
        auth_cls.last_login_throttle_seconds = 60
        user = _CountingUser(last_login=datetime.now())
        _UserClass.current = user

        @auth_cls.auth_required()
        def view():
            return "ok"

        view()
        view()
        view()
        assert user.save_calls == 0

    def test_old_login_triggers_save(self, auth_cls, session):
        auth_cls.last_login_throttle_seconds = 60
        old = datetime.now() - timedelta(seconds=120)
        user = _CountingUser(last_login=old)
        _UserClass.current = user

        @auth_cls.auth_required()
        def view():
            return "ok"

        view()
        assert user.save_calls == 1
        # last_login was bumped to "now" — next call is throttled.
        view()
        assert user.save_calls == 1

    def test_throttle_zero_restores_legacy_behaviour(self, auth_cls, session):
        auth_cls.last_login_throttle_seconds = 0
        user = _CountingUser(last_login=datetime.now())
        _UserClass.current = user

        @auth_cls.auth_required()
        def view():
            return "ok"

        view()
        view()
        view()
        assert user.save_calls == 3


class TestSessionRefreshSkipsWhenUnchanged:
    def test_writes_once_then_skips(self, auth_cls, session):
        auth_cls.last_login_throttle_seconds = 60
        user = _CountingUser(
            last_login=datetime.now(), json_payload='{"pk": 1, "v": 1}'
        )
        _UserClass.current = user

        # Track session writes by counting __setitem__ via a wrapper.
        writes = []
        original_setitem = type(session).__setitem__

        def tracked_setitem(self, key, value):
            writes.append((key, value))
            original_setitem(self, key, value)

        type(session).__setitem__ = tracked_setitem
        try:

            @auth_cls.auth_required()
            def view():
                return "ok"

            view()  # first time: must write
            view()  # session matches, must skip
            view()
        finally:
            type(session).__setitem__ = original_setitem

        user_writes = [w for w in writes if w[0] == "user"]
        assert len(user_writes) == 1, user_writes

    def test_writes_when_user_json_changes(self, auth_cls, session):
        auth_cls.last_login_throttle_seconds = 60
        user = _CountingUser(
            last_login=datetime.now(), json_payload='{"pk": 1, "v": 1}'
        )
        _UserClass.current = user

        writes = []
        original_setitem = type(session).__setitem__

        def tracked_setitem(self, key, value):
            writes.append((key, value))
            original_setitem(self, key, value)

        type(session).__setitem__ = tracked_setitem
        try:

            @auth_cls.auth_required()
            def view():
                return "ok"

            view()  # writes "user"
            user._json = '{"pk": 1, "v": 2}'  # simulate user mutation
            view()  # JSON changed, must write again
        finally:
            type(session).__setitem__ = original_setitem

        user_writes = [w for w in writes if w[0] == "user"]
        assert len(user_writes) == 2
