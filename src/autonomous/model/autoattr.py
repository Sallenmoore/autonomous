from db.fields import (
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
            # log(self.__dict__)
            return super().__get__(instance, owner)
        except DoesNotExist:
            # If the document doesn't exist, return None
            return None

    def validate(self, value):
        if value is not None and not self.required:
            super().validate(value)


class ListAttr(ListField):
    pass
    # @classmethod
    # def clean_references(cls, values):
    #     safe_values = []
    #     for value in values:
    #         try:
    #             if isinstance(value, dict) and "_cls" in value:
    #                 doc_cls = get_document(value["_cls"])
    #                 db = doc_cls._get_collection().database
    #                 value = db.dereference(value["_ref"])
    #             if value:
    #                 safe_values.append(value)
    #         except DoesNotExist:
    #             log(f"Error Cleaning Reference: {value}")
    #     return safe_values if safe_values != values else None


class DictAttr(DictField):
    pass
    # @classmethod
    # def clean_references(cls, values):
    #     safe_values = {}
    #     for key, value in values.items():
    #         try:
    #             if isinstance(value, dict) and "_cls" in value:
    #                 doc_cls = get_document(value["_cls"])
    #                 db = doc_cls._get_collection().database
    #                 value = db.dereference(value["_ref"])
    #             if value:
    #                 safe_values[key] = value
    #         except DoesNotExist:
    #             log(f"Error Cleaning Reference: {key} -- {value}")
    #     return safe_values if safe_values != values else None


class EnumAttr(EnumField):
    pass
