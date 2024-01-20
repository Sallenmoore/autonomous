from datetime import datetime

from autonomous import log
from autonomous.db.autodb import Database


class ORM:
    _database = Database()

    def __init__(self, name, attributes):
        self.table = self._database.get_table(table=name, schema=attributes)
        self.name = name

    def save(self, data):
        return self.table.save(data)

    def get(self, pk):
        return self.table.get(pk)

    def all(self):
        return self.table.all()

    def search(self, **kwargs):
        return self.table.search(**kwargs)

    def find(self, **kwargs):
        return self.table.find(**kwargs)

    def random(self):
        return self.table.random()

    def delete(self, pk):
        return self.table.delete(_id=pk)

    def flush_table(self):
        return self.table.clear()


class AutoEncoder:
    @classmethod
    def encode(cls, objs):
        encoder = cls()
        if isinstance(objs, dict):
            for k, v in objs.items():
                objs[k] = cls.encode(v)
        elif isinstance(objs, list):
            for i, v in enumerate(objs):
                objs[i] = cls.encode(v)
        else:
            return encoder.default(objs)
        return objs

    def default(self, o):
        if hasattr(o, "model_name") and hasattr(o, "pk"):
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
                "_id": o.pk,
                "_automodel": o.model_name(),
            }
        else:
            log(
                o.__class__.__name__,
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

            # breakpoint()
            return DelayedModel(obj["_automodel"], obj["_id"])
        except KeyError:
            log(
                "AutoModel",
                "The above object was not been saved. You must save subobjects if you want them to persist.",
            )
            raise ValueError("Cannot decode unsaved AutoModel")
