#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous.logger import log

import jsonpickle

db = Database()

class Model(BaseModel):

    _attributes = {"pk":int, "model_class":str, "attributes":dict}
    
    def __init__(self, **kwargs):
        
        self.pk = kwargs.get('pk')
        rec = self.table().get(self.pk)
        #log(self.__dict__)
        if rec:
            self.__dict__.update(rec.__dict__)
        for k,v in self.__class__.attributes.items():
            # valid attribute - cast to verify value is valid
            if kwargs.get(k):
                kwargs[k] = self.__class__.attributes[k](kwargs[k])
                #log(f"attribute set: {k}=>{kwargs[k]}", LEVEL="INFO")
            # attribute not set - set to default value
            elif not hasattr(self, k):
                kwargs[k] = self.__class__.attributes[k]()
                #log(f"attribute not set, setting to default: {k}=>{kwargs[k]}", LEVEL="INFO")
            else:
                #log(f" data invalid: {k}=>{v}", LEVEL="INFO")
                pass
                
        self.__dict__.update(kwargs)
        #log(self.__dict__)

    def save(self):
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
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        #log(f"obj: {self}")
        data = cls.table().get(pk)
        #log(f"obj: {data}")
        return cls.deserialize(data)

    ############################## Serialization ########################################
    def serialize(self):
        """
        
        """
        #log(self.__class__.attributes)
        if hasattr(self.__class__, "attributes"):
            self.attributes = self.__class__.attributes
            self.model_class = self.__class__.model_class

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
            elif k == "pk":
                obj_dict[k] = attrib
            else:
                #log(f"no serialize")
                try:
                    #log(f"Attempting cast...")
                    obj_dict[k] = v(attrib) if attrib else None
                except TypeError as e:
                    #log(f"ERROR: {e} -- casting failed")
                    raise
                else:
                    obj_dict[k] = jsonpickle.encode(attrib)
                    #log(f"Cast and serialize successful")
        log(obj_dict)
        return obj_dict
    
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        return [cls.deserialize(obj, **kwargs) for obj in pickled_objs if obj]

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        """
        _summary_

        _extended_summary_
        """

        if not pickled_obj:
            return None
        
        obj_attr = {}
        for k,v in pickled_obj.items():
            try:
                obj_attr[k] = jsonpickle.decode(str(v), **kwargs)
            except Exception as e:
                log(f"[ {e} ] cannot decode data -- {k}: {v}")
            else:
                if hasattr(obj_attr[k], 'deserialize'):
                    obj_attr[k] = obj_attr[k].deserialize(obj_attr[k]) 
        return cls(**obj_attr)