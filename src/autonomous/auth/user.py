"""
This module provides a User class that uses the OpenIDAuth class for authentication.
"""

from datetime import datetime

from autonomous import log
from autonomous.model.autoattr import DateTimeAttr, StringAttr
from autonomous.model.automodel import AutoModel


class AutoUser(AutoModel):
    """
    This class represents a user who can authenticate using OpenID.
    """

    meta = {
        "abstract": True,
        "allow_inheritance": True,
        "strict": False,
    }
    name = StringAttr(default="Anonymous")
    email = StringAttr(required=True)
    last_login = DateTimeAttr(default=datetime.now)
    state = StringAttr(default="unauthenticated")
    provider = StringAttr()
    role = StringAttr(default="guest")
    token = StringAttr()

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
        log(email, user)
        if not user:
            log(f"Creating new user for {email}")
            # user = cls(name=name, email=email)

        # parse user_info into a user object
        user.name = name
        user.email = email
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.save()
        return user

    @classmethod
    def get_guest(cls):
        """
        Returns a guest user.
        """
        guest = cls.find(name="_GuestOfAutonomous_")
        if not guest:
            guest = cls(
                name="_GuestOfAutonomous_",
                email="guest@mail.com",
                state="guest",
                role="guest",
            )
            guest.save()
        return guest

    @property
    def is_authenticated(self):
        """
        Returns True if the user is authenticated, False otherwise.
        """
        return self.state == "authenticated"

    @property
    def is_guest(self):
        """
        Returns True if the user is a guest, False otherwise.
        """
        return not self.is_authenticated or self.role == "guest"

    @property
    def is_admin(self):
        """
        Returns True if the user is a guest, False otherwise.
        """
        return self.is_authenticated and self.role == "admin"


class User(AutoUser):
    """
    This class represents a user who can authenticate using OpenID.
    """

    def __repr__(self):
        return f"<User {self.pk} {self.email}>"
