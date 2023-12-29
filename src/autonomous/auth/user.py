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
        "role": "user",
        "token": None,
    }

    def __eq__(self, other):
        return self.pk == other.pk

    @classmethod
    def authenticate(cls, user_info, token=None):
        """
        Initiates the authentication process.
        Returns a redirect URL which should be used to redirect the user to the OpenID provider for authentication.
        """
        email = user_info["email"].strip()
        name = user_info["name"].strip()
        user = cls.find(email=email)
        if not user:
            # FIXME: attempting a lookup hack because something is fucked up
            for u in cls.all():
                if u.email == email:
                    user = u
        if not user:
            log("Creating new user...")
            if email == "stevenallenmoore@gmail.com":
                raise Exception("New user should not be created")
            user = cls(name=name, email=email)

        # parse user_info into a user object
        user.name = name
        user.email = email
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.save()
        # log(user.pk)
        return user

    @property
    def is_authenticated(self):
        """
        Returns True if the user is authenticated, False otherwise.
        """
        return self.state == "authenticated"

    @classmethod
    def get_guest(cls):
        """
        Returns a guest user.
        """
        return cls(name="Guest", email="guest@mail.com", state="guest", role="guest")

    @property
    def is_guest(self):
        """
        Returns True if the user is a guest, False otherwise.
        """
        return self.state == "guest"
