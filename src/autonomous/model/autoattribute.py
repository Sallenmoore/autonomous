class AutoAttribute:
    def __init__(
        self, type, default=None, required=False, unique=False, primary_key=False
    ):
        if type in [
            "TAG",
            "TEXT",
            "NUMERIC",
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
