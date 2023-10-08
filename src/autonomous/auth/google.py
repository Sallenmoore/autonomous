import os

import requests

from autonomous.auth import AutoAuth


class GoogleAuth(AutoAuth):
    def __init__(self, state=None):
        self.req_uri = (
            "https://www.googleapis.com/oauth2/v2/userinfo?fields=id,email,name,picture"
        )
        client_id = os.environ.get("GOOGLE_AUTH_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_AUTH_CLIENT_SECRET")
        redirect_uri = os.environ.get("GOOGLE_AUTH_REDIRECT_URL")

        scope = os.environ.get("GOOGLE_AUTH_SCOPE", ["openid", "email", "profile"])
        if isinstance(scope, str) and "," in scope:
            scope = scope.split(",")
        gduri = os.environ.get("GOOGLE_DISCOVERY_URL")

        response = requests.get(gduri).json()
        authorize_url = response.get("authorization_endpoint")
        token_endpoint = response.get("token_endpoint")
        super().__init__(
            client_id,
            client_secret,
            authorize_url,
            redirect_uri,
            scope,
            token_endpoint,
            state,
        )
