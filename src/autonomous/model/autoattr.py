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


class ReferenceAttr(GenericReferenceField):
    def __get__(self, instance, owner):
        try:
            result = super().__get__(instance, owner)
        except DoesNotExist as e:
            log(f"ReferenceAttr Error: {e}")
            return None
        return result


# class ReferenceAttr(GenericLazyReferenceField):
#     def __get__(self, instance, owner):
#         try:
#             result = super().__get__(instance, owner)
#         except DoesNotExist as e:
#             log(f"ReferenceAttr Error: {e}")
#             return None
#         return result.fetch() if result and result.pk else result

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
        # print(self.name, self.field, owner, results)
        if isinstance(self.field, ReferenceAttr):
            i = 0
            while i < len(results):
                try:
                    if not results[i]:
                        log(f"Removing Object: {results[i]}")
                        results.pop(i)
                    else:
                        i += 1
                except DoesNotExist:
                    results.pop(i)
                    log(f"Object Not Found: {results[i]}")
        # log(results)
        return results


class DictAttr(DictField):
    def __get__(self, instance, owner):
        # log(instance, owner)
        results = super().__get__(instance, owner) or {}
        # log(self.name, self.field, owner, results)
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
