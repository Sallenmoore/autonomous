"""
    This module provides a User class that uses the OpenIDAuth class for authentication.
"""
from datetime import datetime

from autonomous import log
from autonomous.model.autoattribute import AutoAttribute
from autonomous.model.automodel import AutoModel


class AutoUser(AutoModel):
    """
    This class represents a user who can authenticate using OpenID.
    """

    attributes = {
        "name": AutoAttribute("TEXT", required=True),
        "email": AutoAttribute("TAG", required=True),
        "last_login": datetime.now(),
        "state": "unauthenticated",
        "provider": None,
        "token": None,
    }

    @classmethod
    def authenticate(cls, user_info, token=None):
        """
        Initiates the authentication process.
        Returns a redirect URL which should be used to redirect the user to the OpenID provider for authentication.
        """
        # log(user_info)
        user = cls.find(email=user_info["email"])
        # log(user, user_info)
        if not user:
            # log("Creating new user...")
            user = cls(**user_info)

        # parse user_info into a user object
        user.name = user_info["name"]
        user.email = user_info["email"]
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.save()
        log(user.pk)
        return user

    @property
    def is_authenticated(self):
        """
        Returns True if the user is authenticated, False otherwise.
        """
        return self.state == "authenticated"
