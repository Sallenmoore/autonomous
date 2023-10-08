import json
import uuid

import requests
from authlib.integrations.requests_client import OAuth2Auth, OAuth2Session

from autonomous import log


class AutoAuth:
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
        log(token_endpoint)
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
        log(self.token_endpoint, response)
        token = self.session.fetch_token(
            authorization_response=response,
            state=state,
        )
        # log(token)

        userinfo = requests.get(self.req_uri, auth=OAuth2Auth(token))
        log(userinfo.text)
        return userinfo.json(), token
