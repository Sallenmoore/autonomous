import os

import requests

from autonomous.auth import AutoAuth


class GoogleAuth(AutoAuth):
    provider_name = "google"

    def _extract_sub(self, raw_userinfo):
        """Google's stable subject identifier.

        OIDC's ``sub`` claim is the spec answer, but ``req_uri`` here
        points at ``oauth2/v2/userinfo`` which returns the same value
        under ``id``. Prefer ``sub`` so a future swap to the OIDC
        userinfo endpoint or a discovery-driven config doesn't silently
        change the (provider, sub) identity for existing users.
        """
        return raw_userinfo.get("sub") or raw_userinfo.get("id")

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

        # Bounded and status-checked (#272): a network blip must fail the
        # login fast and loudly rather than hang the worker or parse an
        # error page. ``requests.get`` stays the call (not autoauth's
        # ``_HTTP``) because consumers patch ``autonomous.auth.google.requests.get``.
        resp = requests.get(gduri, timeout=30)
        resp.raise_for_status()
        response = resp.json()
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
