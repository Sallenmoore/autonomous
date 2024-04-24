class DanglingReferenceError(Exception):
    def __init__(self, model, pk, obj):
        self.model = model
        self.pk = pk
        self.obj = obj
        super().__init__(
            f"Reference to a deleted object.\nModel: {model}\npk: {pk}\nResult: {obj}"
        )
