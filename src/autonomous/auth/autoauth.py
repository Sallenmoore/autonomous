import uuid
from datetime import datetime
from functools import wraps

import requests
from authlib.integrations.requests_client import OAuth2Auth, OAuth2Session

from autonomous.auth.user import User
from autonomous.web import get_session, redirect


class AutoAuth:
    user_class: type[User] = User
    login_url: str = "/auth/login"

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
        self.session = OAuth2Session(
            self.client_id,
            client_secret=self.client_secret,
            scope=scope,
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
        Returns (uri, state). Callers redirect the user to ``uri``.
        """
        uri, state = self.session.create_authorization_url(self.issuer)
        return uri, state

    def handle_response(self, response, state=None):
        token = self.session.fetch_token(
            authorization_response=response,
            state=state,
        )
        userinfo = requests.get(self.req_uri, auth=OAuth2Auth(token))
        return userinfo.json(), token

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
                    user.last_login = datetime.now()
                    user.save()
                session["user"] = user.to_json()
                if not guest and user.is_guest:
                    return redirect(cls.login_url)
                if admin and not user.is_admin:
                    return redirect(cls.login_url)
                return func(*args, **kwargs)

            return decorated_view

        return wrap
