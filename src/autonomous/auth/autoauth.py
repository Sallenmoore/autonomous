import uuid
from datetime import datetime
from functools import wraps

import requests
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.requests_client import OAuth2Auth, OAuth2Session

from autonomous.auth.user import User
from autonomous.web import get_session, redirect


class AutoAuth:
    user_class: type[User] = User
    login_url: str = "/auth/login"
    #: Session key under which the issued OAuth ``state`` value is stored
    #: between :meth:`authenticate` and :meth:`handle_response`. Override on
    #: a subclass if multiple providers might collide in the same session.
    state_session_key: str = "oauth_state"
    #: Minimum interval between ``last_login`` DB writes from
    #: :meth:`auth_required`. Set to 0 to write on every authenticated
    #: request (the legacy behaviour).
    last_login_throttle_seconds: int = 60

    def __init__(
        self,
        client_id,
        client_secret,
        issuer,
        redirect_uri,
        scope,
        token_endpoint,
        state=None,
    ):
        self.state = state or uuid.uuid4().hex
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer = issuer
        self.redirect_uri = redirect_uri
        self.token_endpoint = token_endpoint
        self.scope = scope
        self._build_session()

    def _build_session(self):
        self.session = OAuth2Session(
            self.client_id,
            client_secret=self.client_secret,
            scope=self.scope,
            redirect_uri=self.redirect_uri,
            token_endpoint=self.token_endpoint,
            state=self.state,
        )

    @classmethod
    def current_user(cls, pk=None):
        session = get_session()
        if pk:
            user = cls.user_class.get(pk)
        elif session.get("user"):
            user = cls.user_class.from_json(session["user"])
        else:
            user = None

        if not user or user.state != "authenticated":
            user = cls.user_class.get_guest()
        return user

    def authenticate(self):
        """
        Begin the OAuth flow.

        Rotates ``self.state`` on every call so each redirect carries a
        fresh, unguessable nonce, then stores it in the active session under
        :attr:`state_session_key`. :meth:`handle_response` reads it back to
        defeat CSRF on the callback.

        Returns:
            tuple: ``(authorization_url, state)``. Callers redirect the user
            to ``authorization_url``; ``state`` is also returned for callers
            that want to pin it themselves.
        """
        self.state = uuid.uuid4().hex
        self._build_session()
        uri, state = self.session.create_authorization_url(self.issuer)
        get_session()[self.state_session_key] = state
        return uri, state

    def handle_response(self, response, state=None):
        """
        Complete the OAuth flow.

        If ``state`` is not provided, the value stored by
        :meth:`authenticate` is read from the session. A missing or
        mismatched state raises
        :class:`authlib.integrations.base_client.errors.MismatchingStateError`,
        which is the authlib idiom for a CSRF-likely callback.

        On success the session key is cleared so a replayed callback cannot
        be re-validated.
        """
        session = get_session()
        if state is None:
            state = session.get(self.state_session_key)
        if not state:
            raise MismatchingStateError()

        try:
            token = self.session.fetch_token(
                authorization_response=response,
                state=state,
            )
        finally:
            # Burn the state whether the exchange succeeded or raised; a
            # replayed callback must not be re-validated and a fresh
            # authenticate() will mint a new one.
            try:
                del session[self.state_session_key]
            except (KeyError, TypeError):
                pass

        userinfo = requests.get(self.req_uri, auth=OAuth2Auth(token))
        return userinfo.json(), token

    @classmethod
    def _touch_user(cls, user) -> None:
        """Persist ``user.last_login`` at most once per throttle window.

        Avoids a Mongo write on every authenticated request. The first
        request after the throttle interval pays the cost; intervening
        ones are free.
        """
        if cls.last_login_throttle_seconds <= 0:
            user.last_login = datetime.now()
            user.save()
            return
        now = datetime.now()
        last = getattr(user, "last_login", None)
        if last is None or (now - last).total_seconds() >= cls.last_login_throttle_seconds:
            user.last_login = now
            user.save()

    @staticmethod
    def _refresh_session_user(session, user) -> None:
        """Write the user JSON to the session only if it differs.

        Saves the per-request serialization cost when nothing about the
        user has changed.
        """
        payload = user.to_json()
        if session.get("user") != payload:
            session["user"] = payload

    @classmethod
    def auth_required(cls, guest=False, admin=False):
        """
        Decorator that enforces authentication before invoking the view.

        Unauthenticated / disallowed users receive a :class:`Response` 302 to
        ``cls.login_url``. Consumers that use Flask can assign
        ``AutoAuth.login_url = url_for("auth.login")`` at startup; the returned
        Response object is WSGI-callable and can be returned from any view.
        """

        def wrap(func):
            @wraps(func)
            def decorated_view(*args, **kwargs):
                session = get_session()
                user = cls.current_user()
                if not user:
                    return redirect(cls.login_url)
                if user.state == "authenticated":
                    cls._touch_user(user)
                cls._refresh_session_user(session, user)
                if not guest and user.is_guest:
                    return redirect(cls.login_url)
                if admin and not user.is_admin:
                    return redirect(cls.login_url)
                return func(*args, **kwargs)

            return decorated_view

        return wrap
