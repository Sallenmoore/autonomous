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
    GenericLazyReferenceField,
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


class ReferenceAttr(GenericLazyReferenceField):
    def __get__(self, instance, owner):
        try:
            result = super().__get__(instance, owner)
        except DoesNotExist as e:
            log(f"ReferenceAttr Error: {e}")
            return None
        return result.fetch() if result and result.pk else result

    # except DoesNotExist:
    # If the document doesn't exist, return None
    #    return None

    # def validate(self, value):
    #     if value is not None and not self.required:
    #         super().validate(value)


class ListAttr(ListField):
    # pass
    def __get__(self, instance, owner):
        # log(instance, owner)
        results = super().__get__(instance, owner) or []
        # log(self.name, self.field, owner, results)
        if isinstance(self.field, ReferenceAttr):
            for idx, lazy_obj in enumerate(results):
                if lazy_obj:
                    try:
                        real_obj = lazy_obj.fetch()
                        log(f"Real Object: {real_obj}")
                        if real_obj:
                            results[idx] = real_obj
                    except DoesNotExist:
                        log(f"Object Not Found: {lazy_obj}")
                else:
                    results[idx] = None
        # log(results)
        return results


class DictAttr(DictField):
    def __get__(self, instance, owner):
        # log(instance, owner)
        results = super().__get__(instance, owner) or {}
        log(self.name, self.field, owner, results)
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


class EnumAttr(EnumField):
    pass
