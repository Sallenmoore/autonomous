import importlib
import inspect
import json
from collections import namedtuple
from datetime import datetime
from json import JSONEncoder

from autolib.logger import log

from .automodel import AutoModel, AutoObject


class AutoEncoder(JSONEncoder):
    def get_class(module_name, class_name):
        """Return a class instance from a string reference"""
        try:
            module_ = importlib.import_module(module_name)
            try:
                class_ = getattr(module_, class_name)()
            except AttributeError:
                log("Class does not exist", class_name)
        except ImportError:
            log("Module does not exist", module_name)
        return class_ or None

    def default(self, o):

        save_data = {}

        for k, v in o.__dict__.items():

            if k.startswith("_"):
                continue

            try:
                save_data[k] = json.dumps(v)
            except Exception as e:
                log(e)
                save_data[k] = self._serialize(v)

        return save_data

    def _serialize(self, val):
        if isinstance(val, list):
            for i, v in enumerate(val):
                val[i] = self._serialize(v)
        elif isinstance(val, dict):
            for k, v in val.items():
                val[k] = self._serialize(v)
        elif issubclass(val.__class__, AutoModel):
            val.save()
            val = {"pk": val.pk, "automodel": val.__class__.__name__}
        elif isinstance(val, datetime):
            val = {"_autoobject": datetime, "value": val.isoformat()}
        else:
            try:
                json.dumps(val)
            except:
                objtype = ".".join([val.__class__.__module__, val.__class__.__name__])
                val = {"_autoobject": objtype, **val.__dict__}

        return val

    @classmethod
    def _deserialize(cls, val):

        if isinstance(val, dict):
            if "automodel" in val:

                model = AutoModel._auto_models[val["automodel"]]
                val = model(pk=val["pk"])

            elif "_autoobject" in val:

                if val["_autoobject"] == datetime:

                    val = datetime.fromisoformat(val["value"])

                else:

                    objtype = val["_autoobject"]
                    obj_cls = AutoEncoder.get_class(*objtype.rsplit(".", 1))
                    val = obj_cls(**val)

            else:

                for k, v in val.items():
                    val[k] = cls._deserialize(v)

        elif isinstance(val, list):

            for i, v in enumerate(val):
                val[i] = cls._deserialize(v)

        return val

    @classmethod
    def deserialize(cls, data):

        if isinstance(data, list):
            for i, v in enumerate(data):
                data[i] = cls.deserialize(v)

        if not isinstance(data, dict):
            raise Exception(f"Data must be a dict: {data}")

        for k, v in data.items():
            data[k] = cls._deserialize(v)

        return data
