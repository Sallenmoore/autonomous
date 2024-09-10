import importlib

_class_registry_cache = {}
_field_list_cache = []


def _import_class(cls_name):
    """Cache mechanism for imports.

    Due to complications of circular imports autonomous.db needs to do lots of
    inline imports in functions.  This is inefficient as classes are
    imported repeated throughout the autonomous.db code.  This is
    compounded by some recursive functions requiring inline imports.

    :mod:`autonomous.db.common` provides a single point to import all these
    classes.  Circular imports aren't an issue as it dynamically imports the
    class when first needed.  Subsequent calls to the
    :func:`~autonomous.db.common._import_class` can then directly retrieve the
    class from the :data:`autonomous.db.common._class_registry_cache`.
    """
    if cls_name in _class_registry_cache:
        return _class_registry_cache.get(cls_name)

    doc_classes = (
        "Document",
        "DynamicEmbeddedDocument",
        "EmbeddedDocument",
        "MapReduceDocument",
    )

    # Field Classes
    if not _field_list_cache:
        from autonomous.db.fields import __all__ as fields

        _field_list_cache.extend(fields)
        from autonomous.db.base.fields import __all__ as fields

        _field_list_cache.extend(fields)

    field_classes = _field_list_cache

    deref_classes = ("DeReference",)

    if cls_name == "BaseDocument":
        from autonomous.db.base import document as module

        import_classes = ["BaseDocument"]
    elif cls_name in doc_classes:
        from autonomous.db import document as module

        import_classes = doc_classes
    elif cls_name in field_classes:
        from autonomous.db import fields as module

        import_classes = field_classes
    elif cls_name in deref_classes:
        from autonomous.db import dereference as module

        import_classes = deref_classes
    elif cls_name == "AutoModel":
        from autonomous.model import automodel as module

        import_classes = [cls_name]
    else:
        try:
            module_name, model_name = (
                cls_name.rsplit(".", 1)
                if "." in cls_name
                else (f"models.{cls_name.lower()}", cls_name)
            )
            module = importlib.import_module(module_name)
            import_classes = [cls_name]
        except Exception as e:
            raise Exception(f"{e} \n No import set for: {cls_name}")

    for cls in import_classes:
        _class_registry_cache[cls] = getattr(module, cls)

    return _class_registry_cache.get(cls_name)
