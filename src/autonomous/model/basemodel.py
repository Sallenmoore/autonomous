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

    # def get_record(self):
    #     obj_dict = {}
    #     for k,v in self.__dict__.items():
    #         try:
    #             json.dumps(v)
    #         except Exception as e:
    #             log(f"{e}: cannot jsonify attribute {k}: {v}", "INFO")
    #         else:
    #             obj_dict[k] = self.attributes[k](v)
    #     return obj_dict

    ############################## Public Methods #####################################


    ##############################  Properties       #####################################


    ############################## Operators       #####################################

    ############################## Serialization ########################################
    def serialize(self, **kwargs):
        raise NotImplementedError
    
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        raise NotImplementedError

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        raise NotImplementedError
