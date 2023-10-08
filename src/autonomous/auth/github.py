import os

import requests

from autonomous.auth import AutoAuth


class GithubAuth(AutoAuth):
    def __init__(self, state=None):
        self.req_uri = "https://api.github.com/user"
        client_id = os.environ.get("GITHUB_AUTH_CLIENT_ID")
        client_secret = os.environ.get("GITHUB_AUTH_CLIENT_SECRET")
        redirect_uri = os.environ.get("GITHUB_AUTH_REDIRECT_URL")
        scope = os.environ.get("GITHUB_AUTH_SCOPE", ["user:email", "read:user"])
        if isinstance(scope, str) and "," in scope:
            scope = scope.split(",")
        authorize_url = os.environ.get("GITHUB_AUTH_AUTHORIZE_URL")
        token_endpoint = os.environ.get("GITHUB_AUTH_TOKEN_URL")
        super().__init__(
            client_id,
            client_secret,
            authorize_url,
            redirect_uri,
            scope,
            token_endpoint,
            state,
        )
