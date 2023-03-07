import json
from datetime import datetime
from json import JSONEncoder

from autonomous import automodel
from autonomous.logger import log


class AutoEncoder(JSONEncoder):
    @staticmethod
    def _serialize(val):
        if isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = AutoEncoder._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = AutoEncoder._serialize(v)
        elif isinstance(val, datetime):
            val = val.isoformat()
        elif issubclass(val.__class__, automodel.AutoModel):
            val.save()
            val = {"_pk": val.pk, "_automodel": val.__class__.__name__}

        return val

    def default(self, o):
        save_data = {}
        for k, v in o.__dict__.items():
            if k.startswith("_"):
                continue
            try:
                json.dumps(v)
            except Exception as e:
                log(e)
                save_data[k] = AutoEncoder._serialize(v)
            else:
                save_data[k] = v
        return o.serialize(save_data)

    @staticmethod
    def _decode(val):
        if isinstance(val, dict):
            if "_automodel" in val:
                autoclass = filter(
                    lambda klass: val["_automodel"]
                    == klass.__name__.rsplit(".", 1)[-1],
                    automodel.AutoModel.__subclasses__(),
                )
                model = next(autoclass, None)
                # breakpoint()
                val = model(_pk=val["_pk"])
            else:
                for k, v in val.items():
                    val[k] = AutoEncoder._decode(v)
        elif isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = AutoEncoder._decode(v)
        elif isinstance(val, str):
            try:
                val = datetime.fromisoformat(val)
            except Exception as e:
                pass
        return val

    @staticmethod
    def decode(object_dict):

        if not isinstance(object_dict, dict):
            raise Exception(f"Data must be a dict: {object_dict}")
        for k, v in object_dict.items():
            # breakpoint()
            object_dict[k] = AutoEncoder._decode(v)
        # breakpoint()
        return object_dict
