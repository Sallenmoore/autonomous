from mongoengine.base import (
    get_document,
)
from mongoengine.fields import (
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
    pass


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
            # Attempt to retrieve the referenced document
            return super().__get__(instance, owner)
        except DoesNotExist:
            # If the document doesn't exist, return None
            return None

    def validate(self, value):
        if value is not None and not self.required:
            super().validate(value)


class ListAttr(ListField):
    def clean_references(self, values):
        safe_values = []
        updated = False
        for value in values:
            try:
                if isinstance(value, dict) and "_cls" in value:
                    doc_cls = get_document(value["_cls"])
                    value = doc_cls._get_db().dereference(value["_ref"])
                if value:
                    safe_values.append(value)
                else:
                    updated = True
            except DoesNotExist:
                updated = True
        return safe_values, updated


class DictAttr(DictField):
    def clean_references(self, values):
        safe_values = {}
        updated = False
        for key, value in values.items():
            try:
                if isinstance(value, dict) and "_cls" in value:
                    doc_cls = get_document(value["_cls"])
                    value = doc_cls._get_db().dereference(value["_ref"])
                if value:
                    safe_values[key] = value
                else:
                    updated = True
            except DoesNotExist:
                updated = True
        return safe_values, updated


class EnumAttr(EnumField):
    pass
