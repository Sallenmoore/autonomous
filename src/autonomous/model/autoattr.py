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


class EnumAttr(EnumField):
    """An enum-valued attribute. Alias of :class:`EnumField`."""
