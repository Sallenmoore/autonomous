"""Typed attribute descriptors used on ``AutoModel`` subclasses.

Every ``Attr`` class here is a thin wrapper around a mongoengine field
from ``autonomous.db.fields``. They exist as a stable public surface so
consumers can write ``from autonomous.model.autoattr import StringAttr``
without reaching into the fork-internal ``autonomous.db.fields``
namespace.

Most are bare aliases. The ones that add behaviour document it in their
class docstring.
"""

import re

from autonomous.db.fields import (
    BooleanField,
    DateTimeField,
    DictField,
    DoesNotExist,
    EmailField,
    EnumField,
    FileField,
    FloatField,
    GenericReferenceField,
    ImageField,
    IntField,
    ListField,
    StringField,
)

from autonomous import log


class StringAttr(StringField):
    """A unicode string attribute. Alias of :class:`StringField`."""


class IntAttr(IntField):
    """An integer attribute with best-effort string coercion.

    Accepts numeric strings (``"1,234"`` → ``1234``) and extracts the
    first integer substring from non-numeric input (``"$42.50"`` → ``42``).
    Falls through to the parent behaviour for everything else.
    """

    def __set__(self, instance, value):
        if isinstance(value, str):
            value = value.replace(",", "")
            if value.isdigit():
                value = int(value)
            elif num_str := re.search(r"-?\d+", value):
                value = int(num_str.group())
        super().__set__(instance, value)


class FloatAttr(FloatField):
    """A floating-point attribute. Alias of :class:`FloatField`."""


class BoolAttr(BooleanField):
    """A boolean attribute. Alias of :class:`BooleanField`."""


class DateTimeAttr(DateTimeField):
    """A ``datetime`` attribute. Alias of :class:`DateTimeField`."""


class EmailAttr(EmailField):
    """An email-address attribute (validated). Alias of :class:`EmailField`."""


class FileAttr(FileField):
    """A GridFS-backed file attribute. Alias of :class:`FileField`."""


class ImageAttr(ImageField):
    """A GridFS-backed image attribute. Alias of :class:`ImageField`."""


class ReferenceAttr(GenericReferenceField):
    """A reference to another ``AutoModel`` instance.

    Resolves to ``None`` when the referenced document has been deleted
    rather than raising ``DoesNotExist``. Otherwise identical to
    :class:`GenericReferenceField`.
    """

    def __get__(self, instance, owner):
        try:
            return super().__get__(instance, owner)
        except DoesNotExist:
            return None

    def __set__(self, instance, value):
        """Assign *value* and unconditionally mark the field dirty.

        ``GenericReferenceField.__get__`` lazily replaces the raw
        ``{_cls, _ref}`` dict stored in ``instance._data`` with the
        dereferenced ``Document`` object by writing directly to ``_data``,
        bypassing the normal descriptor path.  The base-class equality
        check in ``BaseField.__set__`` then compares a ``Document`` to
        itself (or to a stale dict) and may incorrectly decide the field
        has not changed, leaving ``_changed_fields`` empty.  Explicitly
        calling ``_mark_as_changed`` here ensures the field is always
        included in the next ``$set`` payload regardless of what was
        previously cached in ``_data``.
        """
        if instance._initialised:
            instance._mark_as_changed(self.name)
        super().__set__(instance, value)


class ListAttr(ListField):
    """A list attribute that self-heals.

    Behaviour layered on top of :class:`ListField`:

    - Returns an empty list (and rewrites the stored value) if the
      document somehow contains a non-list under this key.
    - When the list holds ``ReferenceAttr`` values, prunes ``None``
      entries caused by deleted referents in-place on access.
    - On assignment, turns a string with ``;`` or ``,`` separators into
      a list of trimmed substrings; a single non-empty string becomes a
      one-element list; ``""`` becomes ``[]``.
    """

    def __get__(self, instance, owner):
        results = super().__get__(instance, owner)

        if not isinstance(results, list):
            super().__set__(instance, [])
            results = super().__get__(instance, owner)

        if isinstance(self.field, ReferenceAttr):
            i = 0
            while i < len(results):
                try:
                    if not results[i]:
                        results.pop(i)
                    else:
                        i += 1
                except DoesNotExist:
                    results.pop(i)
        return results

    def __set__(self, instance, value):
        new_value = value
        if isinstance(value, str):
            if ";" in value:
                new_value = [v.strip() for v in value.split(";")]
            elif "," in value:
                new_value = [v.strip() for v in value.split(",")]
            elif value:
                new_value = [value]
            else:
                new_value = []
        super().__set__(instance, new_value)


class DictAttr(DictField):
    """A dictionary attribute that eagerly resolves lazy references.

    When the stored dict contains values with a ``fetch()`` method
    (typically ``ReferenceAttr`` placeholders), each value is
    dereferenced on access. Missing referents are logged and the
    placeholder is left in place.
    """

    def __get__(self, instance, owner):
        results = super().__get__(instance, owner) or {}
        if instance is None:
            # Class-level access (``Model.field``) — the base descriptor
            # hands back the field itself and mongoengine's query builder
            # depends on that. It is not stored data; do not inspect it.
            return results
        if not isinstance(results, dict):
            # Issue #225: a field that BECAME a DictAttr in a schema change
            # leaves every pre-change row holding the old shape (usually a
            # list). Walking ``.items()`` on it raised out of the getter, so
            # the read itself 500'd before any consumer could normalize —
            # one legacy row was enough to take down a whole page.
            #
            # Degrade to the declared default and warn instead. The stored
            # value is deliberately LEFT ALONE — unlike ``ListAttr``, which
            # self-heals by rewriting ``_data``. Rewriting here would
            # destroy the very bytes a consumer needs to migrate from, and
            # the next ``save()`` would persist that loss silently.
            log.warning(
                f"{owner.__name__}.{self.name}: stored value is a legacy "
                f"{type(results).__name__}, not a dict "
                f"(pk={getattr(instance, 'pk', None)}). Returning the field "
                "default; migrate the stored value to a dict."
            )
            return self._legacy_default()
        for key, lazy_obj in results.items():
            try:
                if hasattr(lazy_obj, "fetch"):
                    lazy_obj = (
                        lazy_obj.fetch() if lazy_obj and lazy_obj.pk else lazy_obj
                    )
            except DoesNotExist:
                log(f"Object Not Found: {lazy_obj}")
            results[key] = lazy_obj
        return results

    def __set__(self, instance, value):
        super().__set__(instance, value)

    def _legacy_default(self):
        """A fresh dict for the legacy-shape read path.

        ``self.default`` may be a callable (``default=dict``) or a literal
        (``default={"tier": "base"}``). A literal is shared mutable state
        on the field, so it is copied — handing out the same object would
        let one caller's mutation leak into every other legacy row's read.
        A non-dict default (or none at all) degrades to ``{}``, since the
        caller is about to treat this as a dict either way.
        """
        default = self.default() if callable(self.default) else self.default
        return dict(default) if isinstance(default, dict) else {}


class EnumAttr(EnumField):
    """An enum-valued attribute. Alias of :class:`EnumField`."""
