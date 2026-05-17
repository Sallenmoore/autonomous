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
        # Identity check, not truthiness: a future find() override that
        # returned an empty collection / falsy doc instead of None would
        # otherwise trigger an unwanted second bootstrap and memoize a
        # duplicate guest for the rest of process lifetime.
        if guest is None:
            guest = cls(
                name="_GuestOfAutonomous_",
                email="guest@mail.com",
                state="guest",
                role="guest",
            )
            guest.save()
            log(
                f"Bootstrapped new guest doc "
                f"pk={getattr(guest, 'pk', '?')} on {cls.__name__}"
            )
        cls._cached_guest = guest
        # `getattr` default keeps this log defensive against
        # unexpected `find()` returns — the same robustness that
        # motivates the `is None` check above.
        log(
            f"Memoized guest pk={getattr(guest, 'pk', '?')} "
            f"on {cls.__name__}",
            _print=False,
        )
        return guest

    @classmethod
    def _invalidate_guest_cache(cls):
        """Drop the memoized guest doc on this class and every descendant.

        Walks the subclass tree from this class downward so a project with
        sibling AutoUser subclasses (User, AdminUser, …) can call
        ``AutoUser._invalidate_guest_cache()`` once and clear all of them.
        """
        def _walk(c):
            c._cached_guest = None
            for sub in c.__subclasses__():
                _walk(sub)
        _walk(cls)

    @classmethod
    def auto_post_save(cls, sender, document, **kwargs):
        # Bound invalidation to the AutoUser subtree: the post_save signal
        # is wired globally and any AutoModel save reaches this dispatcher,
        # so cross-model name collisions (a non-User document with name
        # "_GuestOfAutonomous_") would otherwise clobber the cache.
        if not isinstance(document, cls):
            return
        if getattr(document, "name", None) != "_GuestOfAutonomous_":
            return
        # Walk the entire AutoUser subtree, not just `cls`'s descendants:
        # saving via AdminUser must also drop User's stale cache, since
        # they share the same Mongo guest document.
        AutoUser._invalidate_guest_cache()

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
