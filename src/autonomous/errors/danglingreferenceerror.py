class DanglingReferenceError(Exception):
    def __init__(self, model, pk, obj):
        self.model = model
        self.pk = pk
        self.obj = obj
        super().__init__(
            f"Model relationship error. Most likely failed to clean up dangling reference.\nModel: {model}\npk: {pk}\nResult: {obj}"
        )
