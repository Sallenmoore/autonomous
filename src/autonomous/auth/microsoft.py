import os

from autonomous.auth import AutoAuth


class MicrosoftAuth(AutoAuth):
    """Microsoft identity platform (Azure AD / personal accounts) OAuth2
    provider.

    Static-endpoint provider, so construction makes no network call —
    mirrors :class:`GithubAuth` rather than the discovery-fetch pattern
    of :class:`GoogleAuth`. The authorize/token endpoints embed a
    tenant segment; ``MICROSOFT_AUTH_TENANT`` (default ``common``,
    which accepts both work/school and personal Microsoft accounts)
    selects it. Full-URL env vars still win when set, for callers
    pinning a single-tenant app registration.
    """

    provider_name = "microsoft"

    def _extract_sub(self, raw_userinfo):
        """Microsoft's stable subject identifier.

        The OIDC userinfo endpoint (``graph.microsoft.com/oidc/userinfo``)
        returns a per-app ``sub`` claim — stable for a given (user, app)
        pair, which is exactly the identity scope we want. ``oid`` (the
        cross-app object id) is the fallback for tokens minted without a
        ``sub``.
        """
        return raw_userinfo.get("sub") or raw_userinfo.get("oid")

    def __init__(self, state=None):
        tenant = os.environ.get("MICROSOFT_AUTH_TENANT", "common")
        self.req_uri = os.environ.get(
            "MICROSOFT_AUTH_USERINFO_URL",
            "https://graph.microsoft.com/oidc/userinfo",
        )
        client_id = os.environ.get("MICROSOFT_AUTH_CLIENT_ID")
        client_secret = os.environ.get("MICROSOFT_AUTH_CLIENT_SECRET")
        redirect_uri = os.environ.get("MICROSOFT_AUTH_REDIRECT_URL")
        scope = os.environ.get("MICROSOFT_AUTH_SCOPE", ["openid", "email", "profile"])
        if isinstance(scope, str) and "," in scope:
            scope = scope.split(",")
        authorize_url = os.environ.get(
            "MICROSOFT_AUTH_AUTHORIZE_URL",
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        )
        token_endpoint = os.environ.get(
            "MICROSOFT_AUTH_TOKEN_URL",
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
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
