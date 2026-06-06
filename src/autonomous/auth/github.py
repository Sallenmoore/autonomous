import os

import requests

from autonomous.auth import AutoAuth


class GithubAuth(AutoAuth):
    provider_name = "github"

    def _extract_sub(self, raw_userinfo):
        """GitHub's stable subject identifier.

        ``/user`` returns a numeric ``id`` (the canonical GitHub user
        ID, stable across username changes). GitHub does not emit an
        OIDC ``sub`` claim on this endpoint, so the base implementation
        would always return ``None``.
        """
        return raw_userinfo.get("id")

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
