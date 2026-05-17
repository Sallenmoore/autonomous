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
        "indexes": ["name"],
    }
    name = StringAttr(default="Anonymous")
    email = StringAttr(required=True)
    last_login = DateTimeAttr(default=datetime.now)
    state = StringAttr(default="unauthenticated")
    provider = StringAttr()
    role = StringAttr(default="guest")
    token = StringAttr()

    # Process-lifetime cache for the singleton guest doc. Set on the concrete
    # subclass (not AutoUser) so each AutoUser subclass keeps its own cache.
    _cached_guest = None

    def __eq__(self, other):
        if other is None or not hasattr(other, "pk"):
            return False
        return self.pk == other.pk

    def __hash__(self):
        return hash(self.pk)

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
            user = cls(name=name, email=email)
        # parse user_info into a user object
        user.name = name
        user.email = email
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.role = "user"
        user.save()
        return user

    @classmethod
    def get_guest(cls):
        """Return the guest user, memoized for process lifetime.

        The guest document is effectively immutable, so we cache it on the
        class to eliminate a MongoDB round-trip on every unauthenticated
        request. Tests / admin tooling can call
        :meth:`_invalidate_guest_cache` to drop the memo.
        """
        cached = cls._cached_guest
        if cached is not None:
            return cached
        guest = cls.find(name="_GuestOfAutonomous_")
        if not guest:
            guest = cls(
                name="_GuestOfAutonomous_",
                email="guest@mail.com",
                state="guest",
                role="guest",
            )
            guest.save()
        cls._cached_guest = guest
        return guest

    @classmethod
    def _invalidate_guest_cache(cls):
        """Drop the memoized guest doc. Test/admin helper."""
        cls._cached_guest = None

    @classmethod
    def auto_post_save(cls, sender, document, **kwargs):
        # Keep the cached guest doc consistent with Mongo: if any code path
        # saves the guest record (initial bootstrap, admin tooling, future
        # migrations), drop the memo so the next get_guest() reloads.
        if getattr(document, "name", None) == "_GuestOfAutonomous_":
            cls._cached_guest = None

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
