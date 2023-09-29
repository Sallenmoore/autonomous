from .autoauth import AutoAuth
import os


class GithubAuth(AutoAuth):
    client_id = os.environ.get("GITHUB_AUTH_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_AUTH_CLIENT_SECRET")
    scope = os.environ.get("GITHUB_AUTH_SCOPE")
    authorize_url = os.environ.get("GITHUB_AUTH_AUTHORIZE_URL")
    redirect_uri = os.environ.get("GITHUB_AUTH_REDIRECT_URL")
    token_endpoint = os.environ.get("GITHUB_AUTH_TOKEN_ENDPOINT")
