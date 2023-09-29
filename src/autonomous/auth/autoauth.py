from abc import ABC, abstractmethod

from authlib.integrations.requests_client import OAuth2Session
from flask import session

from autonomous import log

from .user import AutoUser


class AutoAuth(ABC):
    client_id = ""
    client_secret = ""
    scope = ""  # we want to fetch user's email
    authorize_url = ""
    redirect_uri = ""
    token_endpoint = ""

    def _auth(self):
        self.oidc = OAuth2Session(
            self.client_id,
            client_secret=self.client_secret,
            scope=self.scope,
            redirect_uri=self.redirect_uri,
        )
        authorization_url, user.auth["state"] = self.oidc.authorization_url(
            self.authorize_url
        )
        token = self.client.fetch_token(
            self.token_endpoint, authorization_url=authorization_url
        )
        result = self.oidc.parse_id_token(token)
        user = AutoUser.find({"email": result["email"]})
        if not user:
            user = AutoUser(
                name=result["name"],
                email=result["email"],
                auth={
                    "state": "authenticated",
                    "token": token,
                    "provider": self.__class__.__name__,
                },
            )
            user.save()
        return user

    def authorize(self):
        if session.get("user") and session["user"].auth["state"] == "authenticated":
            return True
        else:
            user = self._auth()
            log(f"User {user.name} logged in with status {user.auth['state']}")
            return user.auth["state"]
