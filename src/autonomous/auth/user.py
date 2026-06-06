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
    # OIDC-stable identity (#40). ``oauth_provider`` names the IdP
    # ("google", "github", "apple", ...). ``oauth_sub`` is the ``sub``
    # claim from that provider's ID token (or its provider-specific
    # equivalent, e.g. Google's ``id`` from oauth2/v2/userinfo, GitHub's
    # numeric ``id``). The pair is the canonical stable identity:
    # email can change at the provider; the OIDC ``sub`` claim cannot.
    # Empty on legacy records — ``authenticate`` falls back to email
    # lookup when both fields are unset, then backfills on next login.
    oauth_provider = StringAttr()
    oauth_sub = StringAttr()

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
        Resolve or create the User for an OAuth callback's user_info dict.

        Lookup priority (#40): when ``user_info`` carries both
        ``oauth_provider`` and ``oauth_sub`` (the OIDC-stable pair the
        AutoAuth subclasses now inject), look up by that compound key
        first — stable across provider-side email changes and across
        users adding a second provider. Fall back to email lookup for
        legacy records that pre-date the (provider, sub) fields; on a
        successful email-match the OAuth identity is backfilled so the
        next login uses the preferred path — but ONLY when the matched
        record has no existing (provider, sub) bound to a different
        provider, so a user who signs in via Google then via GitHub
        (same email) doesn't have their stored Google pair overwritten.

        Existing call sites that pass plain ``{"name", "email"}``
        user_info dicts (tests, consumers not yet migrated) keep working
        — the (provider, sub) branch is skipped when those keys are
        absent. ``email`` is optional for the LOOKUP side (the
        (provider, sub) path skips email entirely; an absent email also
        won't overwrite a record matched by the pair) but NEW-USER
        creation still requires a non-empty email because
        :attr:`AutoUser.email` is ``required=True`` at the schema layer.
        Callers integrating with providers that omit email under the
        configured scope (GitHub with no ``user:email`` scope, etc.)
        must either (a) configure the provider to request email scope,
        or (b) override :meth:`authenticate` on a subclass to provide a
        fallback identity. Calling this method with ``email=None`` for
        a not-yet-registered user raises ``ValueError`` at the OAuth
        boundary rather than letting MongoEngine surface a generic
        ValidationError deep in the save path — diagnostic-attributable.
        """
        raw_email = user_info.get("email")
        email = raw_email.strip() if raw_email else None
        raw_name = user_info.get("name") or ""
        name = raw_name.strip()
        oauth_provider = user_info.get("oauth_provider")
        oauth_sub = user_info.get("oauth_sub")
        # Coerce to str so callers passing a raw int sub (GitHub /user
        # returns numeric ``id``; tests sometimes mirror that) match
        # the StringAttr-stored value persisted by previous logins.
        oauth_sub_str = str(oauth_sub) if oauth_sub is not None else None

        user = None
        matched_by_oauth = False
        if oauth_provider and oauth_sub_str:
            user = cls.find(oauth_provider=oauth_provider, oauth_sub=oauth_sub_str)
            if user is not None:
                matched_by_oauth = True
        if user is None and email:
            user = cls.find(email=email)
        log(email, user)
        if not user:
            if not email:
                # New-user creation needs a non-empty email — the
                # schema (StringAttr(required=True) on AutoUser.email)
                # blocks save() otherwise, and a ValidationError surfacing
                # from deep in MongoEngine is hard to attribute. Raise
                # at the OAuth boundary so the operator can see the
                # provider/scope misconfiguration directly.
                raise ValueError(
                    f"Cannot create new user for OAuth "
                    f"(provider={oauth_provider!r}, sub={oauth_sub_str!r}): "
                    "no email available. The provider's userinfo did "
                    "not include an email claim — likely the OAuth "
                    "client needs additional scope (e.g. 'user:email' "
                    "for GitHub) or a subclass override of authenticate."
                )
            log(f"Creating new user for {email}")
            user = cls(name=name, email=email)
        # Backfill OIDC identity:
        # - matched_by_oauth: just stamp (same pair, idempotent).
        # - record found via email AND no existing oauth_provider:
        #   safe to claim — this is a legacy upgrade.
        # - record found via email WITH a different existing
        #   oauth_provider: do NOT overwrite. A user has two records'
        #   worth of identity on one email; preserving the original
        #   pair stops the second provider's login from churning it.
        if oauth_provider and oauth_sub_str:
            existing_provider = getattr(user, "oauth_provider", None)
            if matched_by_oauth or not existing_provider:
                user.oauth_provider = oauth_provider
                user.oauth_sub = oauth_sub_str
        user.name = name
        if email:
            user.email = email
        user.last_login = datetime.now()
        user.state = "authenticated"
        user.role = "user"
        user.save()
        return user

    @classmethod
    def get_guest(cls):
        """Return the guest user, memoized class-side (doc is effectively immutable)."""
        cached = cls._cached_guest
        if cached is not None:
            return cached
        guest = cls.find(name="_GuestOfAutonomous_")
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
                f"pk={getattr(guest, 'pk', '?')} on {cls.__name__}",
                _print=False,
            )
        cls._cached_guest = guest
        log(
            f"Memoized guest pk={getattr(guest, 'pk', '?')} "
            f"on {cls.__name__}",
            _print=False,
        )
        return guest

    @classmethod
    def _invalidate_guest_cache(cls):
        """Drop the memoized guest on this class and every descendant."""
        def _walk(c):
            c._cached_guest = None
            for sub in c.__subclasses__():
                _walk(sub)
        _walk(cls)

    @classmethod
    def auto_post_save(cls, sender, document, **kwargs):
        if not isinstance(document, cls):
            return
        if getattr(document, "name", None) != "_GuestOfAutonomous_":
            return
        # Walk from AutoUser (not cls) so sibling subclass caches drop too.
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
