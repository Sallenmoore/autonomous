#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous.logger import log

import jsonpickle

db = Database()

class Model(BaseModel):

    _attributes = {"pk":int, "model_class":str, "attributes":dict}
    
    def __init__(self, **kwargs):
        #log(LEVEL="DEBUG")
        self.pk = kwargs.get('pk')
        
        if rec:= self.table().get(self.pk):
            self.__dict__.update(rec.__dict__)
            
        #log(self.__class__.__name__,kwargs)
        self.__dict__.update(kwargs)
        self.validate()
        #log(self.__class__.__name__,self.__dict__)

    def __getattr__(self, attr):

        if attr in self.attributes:
            return None

        raise AttributeError
    
    def save(self):
        log(LEVEL="DEBUG")
        """
        save() :save object to db
        """
        #log(self)
        self.pk = self.__class__.table().update(self.serialize())
        return self.pk

    def delete(self):
        self.__class__.table().delete(self.pk)

    ################## class methods ####################
    @classmethod
    def table(cls):
        if not hasattr(cls, "_table") or not cls._table:
            cls.model_class = cls.__name__
            cls._table = db.get_table(cls.model_class)
            try:
                cls.attributes.update(Model._attributes)
            except AttributeError:
                log("""
                    Models must have a class variable called 'attributes' that is a dict in the form:
                    attributes = {"attribute_name":attribute_type}
                """)
                raise
        return cls._table
    
    @classmethod
    def all(cls):
        return cls.deserialize_list(cls.table().all())
    
    @classmethod
    def search(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        #log(f"kwargs: {kwargs}")
        results = cls.table().search(**kwargs)
        return cls.deserialize_list(results)

    @classmethod
    def get(cls, pk=None):
        #log(LEVEL="DEBUG")
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        #log(f"obj: {self}")
        data = cls.table().get(pk)
        #log(f"obj: {data}")
        ddata = cls.deserialize(data)
        #log(f"obj: {ddata}")
        return ddata

    ############################## Serialization ########################################
    def validate(self):
        for k,v in self.__dict__.items():
            # valid attribute - cast to verify value is valid
            if k in self.__class__.attributes and self.__class__.attributes[k] != type(v):
                try:
                    setattr(self, k, self.__class__.attributes[k](v))
                except Exception as e:
                    log(f"ERROR: {e} -- casting {k} to {self.__class__.attributes[k]} failed")
                    setattr(self, k, None) #NOT SURE ABOUT THIS - MAYBE JUST RAISE ERROR to enforce strict typing?
                    
    def serialize(self):
        #log(LEVEL="INFO")
        """
        
        """
        #log(self)
        self.attributes = self.__class__.attributes
        self.model_class = self.__class__.model_class
        self.validate()
        
        obj_dict = {}
        for k,v in self.__class__.attributes.items():
            try:
                attrib = getattr(self, k)
            except:
                continue

            #log(f"{self.__class__}", f"{self.__dict__}", f"{k} = {attrib}", f"actual type: {type(attrib)}", f"expected type: {v}")
            if hasattr(attrib, "serialize"):
                #log(f"\nserializing...")
                obj_dict[k] = attrib.serialize()
            else:
                obj_dict[k] = jsonpickle.encode(attrib)
                    #log(f"Cast and serialize successful")
        #log(obj_dict)
        return obj_dict
    
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        return [cls.deserialize(obj, **kwargs) for obj in pickled_objs if obj]

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        #log(pickled_obj)
        """
        _summary_

        _extended_summary_
        """

        if not pickled_obj:
            return None
        
        obj_attr = {}
        for k,v in pickled_obj.items():
            if isinstance(v, dict):
                log(k, v)
                obj_attr[k] = cls.attributes[k].deserialize(v)
            else:
                try:
                    obj_attr[k] = jsonpickle.decode(v, **kwargs)
                except Exception as e:
                    log(f"[ {e} ] cannot decode data -- {k}: {v}")
        #log(obj_attr)
        return cls(**obj_attr)