#local modules
from autonomous.db.db import Database
from autonomous.logger import log

#python modules
import jsonpickle
import json
import copy

db = Database()

class BaseModel():

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        text = "{\n"
        for k,v in vars(self).items():
            text += f"\t{k} : {v} ({type(v)})\n"
        text += "}"
        return text

    def __getstate__(self):
        #log(self.__class__.attributes)
        if not hasattr(self.__class__, "attributes"):
            return self.__dict__
        else:
            self.attributes = self.__class__.attributes
            self.model_class = self.__class__.model_class

        obj_dict = {}
        for k,v in self.__dict__.items():
            if k in self.__class__.attributes and v:
                obj_dict[k] = self.__class__.attributes[k](v)
                # log(f"(serialzed attribute {k}: {obj_dict[k]}")
            else:
                log(f"attribute/value invalid: {k}:{v}", LEVEL="DEBUG")
                obj_dict[k] = None
        return obj_dict

    def get_record(self):
        obj_dict = {}
        for k,v in self.__dict__.items():
            try:
                json.dumps(v)
            except Exception as e:
                log(f"{e}: cannot jsonify attribute {k}: {v}", "DEBUG")
            else:
                obj_dict[k] = self.attributes[k](v)
        return obj_dict

############################## Public Methods #####################################
    def serialize(self, **kwargs):
        """
        
        """
        return jsonpickle.encode(self, **kwargs)

    ##############################  Properties       #####################################


    ############################## Operators       #####################################
    def __EQ__(self, other):
        return self.pk == other.pk

    ############################## Class Methods ########################################
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        return [cls.deserialize(obj, **kwargs) for obj in pickled_objs if obj]

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        #log(f"pickled: {pickled_obj}")
        result = jsonpickle.decode(pickled_obj, **kwargs)
        #log(f"unpickled: {result}")
        return result

