import os

from autonomous.auth import AutoAuth


class DiscordAuth(AutoAuth):
    """Discord OAuth2 provider.

    Static-endpoint provider (no discovery doc), so construction makes
    no network call — mirrors :class:`GithubAuth`. Well-known endpoints
    are baked in as defaults and overridable via ``DISCORD_AUTH_*`` env
    vars.
    """

    provider_name = "discord"

    def _extract_sub(self, raw_userinfo):
        """Discord's stable subject identifier.

        ``/users/@me`` returns a numeric snowflake ``id`` that is stable
        across username changes (Discord usernames are mutable; the
        snowflake is not). Discord does not emit an OIDC ``sub`` claim
        on this endpoint.
        """
        return raw_userinfo.get("id")

    def __init__(self, state=None):
        self.req_uri = os.environ.get(
            "DISCORD_AUTH_USERINFO_URL",
            "https://discord.com/api/users/@me",
        )
        client_id = os.environ.get("DISCORD_AUTH_CLIENT_ID")
        client_secret = os.environ.get("DISCORD_AUTH_CLIENT_SECRET")
        redirect_uri = os.environ.get("DISCORD_AUTH_REDIRECT_URL")
        scope = os.environ.get("DISCORD_AUTH_SCOPE", ["identify", "email"])
        if isinstance(scope, str) and "," in scope:
            scope = scope.split(",")
        authorize_url = os.environ.get(
            "DISCORD_AUTH_AUTHORIZE_URL",
            "https://discord.com/oauth2/authorize",
        )
        token_endpoint = os.environ.get(
            "DISCORD_AUTH_TOKEN_URL",
            "https://discord.com/api/oauth2/token",
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
