from mongoengine.fields import (
    BooleanField,
    DateTimeField,
    DictField,
    EmailField,
    EnumField,
    FileField,
    FloatField,
    ImageField,
    IntField,
    ListField,
    ReferenceField,
    StringField,
)
from mongoengine.queryset import NULLIFY


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


class ReferenceAttr(ReferenceField):
    def __init__(self, document_type, *args, **kwargs):
        if "reverse_delete_rule" not in kwargs:
            kwargs["reverse_delete_rule"] = NULLIFY
        super().__init__(document_type, *args, **kwargs)


class ListAttr(ListField):
    pass


class DictAttr(DictField):
    pass


class EnumAttr(EnumField):
    pass
