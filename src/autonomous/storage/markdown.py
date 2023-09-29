class Page:
    """
    Creates a Page object that can be converted to amrkdown and pushed to a wiki
    Object must be:
        - a dict
        - a class with a __dict__ attribute
        - a class with a serialize() method
    The default wiki is the built in WIkiJS container. Overwrite with your own wiki API by setting the `wiki_api` class attribute.
    Inherit from autonomous.wiki.Wiki abstract class for the required interface.
    """

    wiki_api = None

    def __init__(self, obj):
        if hasattr(obj, "serialize()"):
            self.obj = obj.serialize()
        elif hasattr(obj, "__dict__"):
            self.obj = obj.__dict__
        elif isinstance(obj, dict):
            self.obj = obj
        else:
            raise TypeError(f"Cannot create Page from {type(obj)}")

    def __str__(self):
        return f"Page(title={self.title}, content={self.content})"

    def __repr__(self):
        return str(self)
