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
    pass


class IntAttr(IntField):
    def __set__(self, instance, value):
        if isinstance(value, str):
            value = value.replace(",", "")
            if value.isdigit():
                value = int(value)
            elif num_str := re.search(r"-?\d+", value):
                value = int(num_str.group())
        super().__set__(instance, value)


class FloatAttr(FloatField):
    pass


class BoolAttr(BooleanField):
    pass


class DateTimeAttr(DateTimeField):
    pass


class EmailAttr(EmailField):
    pass


class FileAttr(FileField):
    pass


class ImageAttr(ImageField):
    pass


class ReferenceAttr(GenericReferenceField):
    def __get__(self, instance, owner):
        try:
            return super().__get__(instance, owner)
        except DoesNotExist:
            return None


class ListAttr(ListField):
    def __get__(self, instance, owner):
        results = super().__get__(instance, owner)

        # Defensive: a corrupted document or fresh init can leave the
        # field in a non-list state; reset to empty so downstream code
        # doesn't choke on len() / iteration.
        if not isinstance(results, list):
            super().__set__(instance, [])
            results = super().__get__(instance, owner)

        if isinstance(self.field, ReferenceAttr):
            # Drop dangling references in-place (deleted documents leave
            # ``None`` placeholders the upstream ListField doesn't prune).
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
    pass
