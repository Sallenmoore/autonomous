class AutoAttribute:
    def __init__(
        self, type, default=None, required=False, unique=False, primary_key=False
    ):
        if type in [
            "TEXT",
            "NUMERIC",
            "MODEL",
        ]:
            self.type = type
        else:
            raise ValueError(f"Invalid type {type}")

        self.default = default
        self.required = required
        self.unique = unique
        self.primary_key = primary_key

    def __repr__(self):
        return f"<AutoAttribute {self.type} {self.default} {self.required} {self.unique} {self.primary_key}>"

    def type_check(self, value):
        if self.type == "TEXT":
            if not isinstance(value, str):
                raise TypeError(f"Value must be a string, not {type(value)}")
        elif self.type == "NUMERIC":
            if not isinstance(value, (int, float)):
                raise TypeError(f"Value must be a number, not {type(value)}")
        elif self.type == "MODEL":
            if value is not None or value.__class__.__name__ not in [
                "AutoModel",
                "DelayedModel",
            ]:
                raise TypeError(
                    f"Value must be an AutoModel or None, not {type(value)}"
                )
        else:
            raise ValueError(f"Invalid type {self.type}")
