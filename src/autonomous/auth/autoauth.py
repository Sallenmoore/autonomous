import uuid
from datetime import datetime
from functools import wraps

import requests
from authlib.integrations.requests_client import OAuth2Auth, OAuth2Session
from flask import current_app, redirect, request, session, url_for

from autonomous import log
from autonomous.auth.user import AutoUser


class AutoAuth:
    current_user = None

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
        """
        Initializes the OpenIDAuth object with the client ID, client secret, and issuer URL.
        """
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

    def authenticate(self):
        """
        Initiates the authentication process.
        Returns a redirect URL which should be used to redirect the user to the OpenID provider for authentication.
        """
        uri, state = self.session.create_authorization_url(self.issuer)
        # log(uri, state)
        return uri, state

    def handle_response(self, response, state=None):
        """
        Handles the authentication response from the OpenID provider.
        The response should be a dictionary containing the OpenID provider's response.
        """
        token = self.session.fetch_token(
            authorization_response=response,
            state=state,
        )
        # log(token)

        userinfo = requests.get(self.req_uri, auth=OAuth2Auth(token))
        return userinfo.json(), token

    def auth_required(func):
        """
        If you decorate a view with this, it will ensure that the current user is
        logged in and authenticated before calling the actual view. For
        example:

            @app.route('/post')
            @auth_required
            def post():
                pass

        - params:
          - func: The view function to decorate.
            - type: function
        """

        @wraps(func)
        def decorated_view(*args, **kwargs):
            if current_app:  # with current_app.app_context():
                # log(AutoAuth.current_user, session.get("user"))
                if session.get("user") and session["user"]["state"] == "authenticated":
                    AutoAuth.current_user = AutoUser(**session.get("user"))
                    AutoAuth.current_user.last_login = datetime.now()
                    AutoAuth.current_user.save()
                    session["user"] = AutoAuth.current_user.serialize()
                    return func(*args, **kwargs)
                else:
                    return redirect(url_for("auth.login"))

        return decorated_view
