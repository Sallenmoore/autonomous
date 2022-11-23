#local modules
from autonomous.db.db import Database
from autonomous.logger import log

#python modules
import jsonpickle
import json

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
    


    ############################## Public Methods #####################################

                    
    ##############################  Properties       #####################################


    ############################## Operators       #####################################

    ################## boolean methods ####################

    @classmethod
    def is_auto_model(cls, obj):
        return isinstance(obj, dict) and "_auto_pk" in obj  

    ############################## Serialization ########################################
    def serialize(self, **kwargs):
        raise NotImplementedError
    
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        raise NotImplementedError

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        raise NotImplementedError

    @classmethod
    def model_loader(cls, name):
        from autonomous.model.model import Model
        from autonomous.model.proxymodel import ProxyModel
        
        for c in Model.__subclasses__() + ProxyModel.__subclasses__():
            log(name, c.__name__, LEVEL="DEBUG")
            if name == c.__name__:
                return c


