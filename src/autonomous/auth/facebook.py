import os

from autonomous.auth import AutoAuth


class FacebookAuth(AutoAuth):
    """Facebook Login (Graph API) OAuth2 provider.

    Static-endpoint provider (no discovery doc), so construction makes
    no network call — mirrors :class:`GithubAuth`. The well-known
    Graph API endpoints are baked in as defaults and overridable via
    ``FACEBOOK_AUTH_*`` env vars for callers pinning a specific Graph
    API version.
    """

    provider_name = "facebook"

    def _extract_sub(self, raw_userinfo):
        """Facebook's stable subject identifier.

        The Graph ``/me`` endpoint returns an app-scoped ``id`` that is
        stable for a given (user, app) pair. Facebook does not emit an
        OIDC ``sub`` claim here, so the base implementation would always
        return ``None``.
        """
        return raw_userinfo.get("id")

    def __init__(self, state=None):
        self.req_uri = os.environ.get(
            "FACEBOOK_AUTH_USERINFO_URL",
            "https://graph.facebook.com/me?fields=id,name,email,picture",
        )
        client_id = os.environ.get("FACEBOOK_AUTH_CLIENT_ID")
        client_secret = os.environ.get("FACEBOOK_AUTH_CLIENT_SECRET")
        redirect_uri = os.environ.get("FACEBOOK_AUTH_REDIRECT_URL")
        scope = os.environ.get("FACEBOOK_AUTH_SCOPE", ["email", "public_profile"])
        if isinstance(scope, str) and "," in scope:
            scope = scope.split(",")
        authorize_url = os.environ.get(
            "FACEBOOK_AUTH_AUTHORIZE_URL",
            "https://www.facebook.com/v19.0/dialog/oauth",
        )
        token_endpoint = os.environ.get(
            "FACEBOOK_AUTH_TOKEN_URL",
            "https://graph.facebook.com/v19.0/oauth/access_token",
        )
        super().__init__(
            client_id,
            client_secret,
            authorize_url,
            redirect_uri,
            scope,
            token_endpoint,
            state,
        )
