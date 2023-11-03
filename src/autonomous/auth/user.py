"""
    This module provides a User class that uses the OpenIDAuth class for authentication.
"""
from datetime import datetime

from autonomous import log
from autonomous.model.automodel import AutoModel, AutoField


class AutoUser(AutoModel):
    """
    This class represents a user who can authenticate using OpenID.
    """

    name: str = AutoField(index=True)
    email: str = AutoField(index=True)
    last_login: datetime = datetime.now()
    state: str = "unauthenticated"
    provider: str = ""

    @classmethod
    def authenticate(cls, user_info, token=None):
        """
        Initiates the authentication process.
        Returns a redirect URL which should be used to redirect the user to the OpenID provider for authentication.
        """
        # print(user_info)
        user = AutoUser.find(AutoUser.email == user_info.get("email"))
        print(user, user_info)
        if not user:
            print("Creating new user...")
            user = AutoUser(**user_info)

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
