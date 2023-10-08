"""
    This module provides a User class that uses the OpenIDAuth class for authentication.
"""
from datetime import datetime

from autonomous import AutoModel, log


class AutoUser(AutoModel):
    """
    This class represents a user who can authenticate using OpenID.
    """

    attributes = {
        "name": "",
        "email": "",
        "last_login": datetime.now(),
        "state": "unauthenticated",
        "token": "",
        "provider": None,
    }

    @classmethod
    def authenticate(cls, user_info, token=None):
        """
        Initiates the authentication process.
        Returns a redirect URL which should be used to redirect the user to the OpenID provider for authentication.
        """
        log(user_info)
        user = AutoUser.find(email=user_info.get("email"))
        if not user:
            user = AutoUser()

        # parse user_info into a user object
        user.name = user_info["name"]
        user.email = user_info["email"]
        user.token = token
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.save()
        return user

    @property
    def is_authenticated(self):
        """
        Returns True if the user is authenticated, False otherwise.
        """
        return self.state == "authenticated"
