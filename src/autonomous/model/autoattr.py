from autonomous import log
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


class StringAttr(StringField):
    pass


class IntAttr(IntField):
    pass
    # def __set__(self, instance, owner):
    #     results = super().__get__(instance, owner)
    #     return results


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
            result = super().__get__(instance, owner)
        except DoesNotExist as e:
            # log(f"ReferenceAttr Error: {e}")
            return None
        return result


class ListAttr(ListField):
    def __get__(self, instance, owner):
        results = super().__get__(instance, owner)

        # sanity check
        if not isinstance(results, list):
            super().__set__(instance, [])
            results = super().__get__(instance, owner)

        # log(f"ListAttr: {results}")
        if isinstance(self.field, ReferenceAttr):
            i = 0
            while i < len(results):
                try:
                    if not results[i]:
                        # log(f"Removing Object: {results[i]}")
                        results.pop(i)
                    else:
                        i += 1
                except DoesNotExist:
                    results.pop(i)
                    # log(f"Object Not Found: {results[i]}")
        return results


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

    # def __set__(self, instance, value):
    #     import traceback

    #     traceback.print_stack()

    #     log(value, instance.player_messages, _print=True)
    #     result = super().__set__(instance, value) or {}
    #     log(value, instance.player_messages, _print=True)
    #     return result


class EnumAttr(EnumField):
    pass
