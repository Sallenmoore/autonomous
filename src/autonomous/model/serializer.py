from datetime import datetime

from autonomous import log
from autonomous.errors import DanglingReferenceError


class AutoEncoder:
    @classmethod
    def encode(cls, objs):
        try:
            if isinstance(objs, dict):
                obj_copy = {k: cls.encode(v) for k, v in objs.items()}
            elif isinstance(objs, list):
                obj_copy = [cls.encode(v) for v in objs]
            else:
                obj_copy = cls().default(objs)
            return obj_copy
        except DanglingReferenceError as e:
            log(e)
            return None

    def default(self, o):
        from autonomous.model.automodel import AutoModel, DelayedModel

        if issubclass(type(o), (AutoModel, DelayedModel)):
            name = "AutoModel"
        else:
            name = type(o).__name__

        encoder_name = f"encode_{name}"

        try:
            encoder = getattr(self, encoder_name)
        except AttributeError:
            return o
        else:
            encoded = {"__extended_json_type__": name, "value": encoder(o)}

        return encoded

    def encode_datetime(self, o):
        return o.isoformat()

    def encode_AutoModel(self, o):
        if o.pk:
            return {
                "pk": o.pk,
                "_automodel": o.model_name(qualified=True),
            }
        else:
            log(
                o,
                "The above object was not been saved. You must save subobjects if you want them to persist.",
            )
            raise ValueError("Cannot encode unsaved AutoModel")


class AutoDecoder:
    @classmethod
    def decode(cls, objs):
        decoder = cls()
        if isinstance(objs, dict):
            if "__extended_json_type__" in objs:
                objs = decoder.default(objs)
            else:
                for k, v in objs.items():
                    objs[k] = cls.decode(v)
        elif isinstance(objs, list):
            for i, v in enumerate(objs):
                objs[i] = cls.decode(v)
        return objs

    def default(self, obj):
        try:
            name = obj["__extended_json_type__"]
            decoder_name = f"decode_{name}"
            decoder = getattr(self, decoder_name)
        except (KeyError, AttributeError, TypeError):
            return obj
        else:
            return decoder(obj)

    def decode_datetime(self, o):
        return datetime.fromisoformat(o["value"])

    def decode_AutoModel(self, o):
        obj = o["value"]
        try:
            from autonomous.model.automodel import DelayedModel

            if not obj["pk"]:
                raise KeyError
            return DelayedModel(obj["_automodel"], obj["pk"])
        except KeyError:
            log(
                "AutoModel",
                "The above object was not been saved. You must save subobjects if you want them to persist.",
            )
            raise ValueError("Cannot decode unsaved AutoModel")
