#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous.logger import log

import jsonpickle

db = Database()

class Model(BaseModel):

    _attributes = {"pk":int, "model_class":str, "attributes":dict}
    
    def __init__(self, **kwargs):
        for k,v in self.__class__.attributes.items():
            setattr(self, k, None)
            
        self.pk = kwargs.get('pk')
            
        if rec:= self.table().get(self.pk):
            self.__dict__.update(rec.__dict__)
            
        #log(self.__class__.__name__,kwargs)
        self.__dict__.update(kwargs)
        self.validate()
        #log(self.__class__.__name__,self.__dict__)
    
    def save(self):
        """
        save(): save object to db
        """
        #log(self)
        #save any submodels
        for key, val in self.__dict__.items():
            #log(type(val), isinstance(val, Model))
            if isinstance(val, Model):
                val.save()
            elif isinstance(val, list):
                for i, v in enumerate(val):
                    if isinstance(v, Model):
                        v.save()

        #log(self)
        serialized_obj = self.serialize()
        #log(serialized_obj)
        self.pk = self.__class__.table().update(serialized_obj)
        return self.pk

    def delete(self, keep_related=False):
        if not keep_related:
            for k,v in self.__dict__.items():
                if isinstance(v, Model):
                    v.delete()
        self.__class__.table().delete(self.pk)

    ################## class methods ####################
    @classmethod
    def table(cls):
        if not hasattr(cls, "_table") or not cls._table:
            cls.model_class = cls.__name__
            cls._table = db.get_table(cls.model_class)
            cls.attributes.update(Model._attributes)
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
        log(LEVEL="DEBUG")
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        if not pk:
            return None
        
        data = cls.table().get(pk)
        #log(f"obj: {data}")
        ddata = cls.deserialize(data)
        #log(f"obj: {ddata}")
        return ddata

    ############################## Serialization ########################################
    def validate(self):
        for k,v in self.__dict__.items():
            # valid attribute - verify value is valid
            if v and k in self.__class__.attributes:
                #check if it is a model object
                if issubclass(self.__class__.attributes[k], Model):
                    assert isinstance(v, Model) or "__auto_pk" in v
                elif self.__class__.attributes[k] != type(v):
                    try:
                        setattr(self, k, self.__class__.attributes[k](v))
                    except Exception as e:
                        log(f"type not equal k:{k} v:{v}", e, LEVEL="DEBUG")

    def serialize(self, full_object=False):
        #log(LEVEL="INFO")
        """
        
        """
        #log(self)
        self.attributes = self.__class__.attributes
        self.model_class = self.__class__.model_class
        self.validate()
        
        obj_dict = {}
        for k,v in self.__class__.attributes.items():
            log(f" k:{k} v:{v}", LEVEL="DEBUG")

            try:
                attrib = getattr(self, k)
            except:
                continue

            log(f" {k}:{attrib}", LEVEL="DEBUG")
            
            if not full_object:
                if isinstance(attrib, Model):
                    attrib = {"__auto_pk":attrib.pk, "__auto_model":v}
                elif isinstance(attrib, list):
                    for i, o in enumerate(attrib):
                        if isinstance(o, Model):
                            attrib[i] = {"__auto_pk":o.pk, "__auto_model":o.__class__}
            log(f" {k}:{attrib}", LEVEL="DEBUG")

            obj_dict[k] = jsonpickle.encode(attrib)
            #log(f" obj_dict[k]:{obj_dict[k]}", LEVEL="DEBUG")
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
            try:
                obj_attr[k] = jsonpickle.decode(v, **kwargs)
            except Exception as e:
                log(f"[ {e} ] cannot decode data -- {k}: {v}", LEVEL="DEBUG")
                continue
            if isinstance(obj_attr[k], dict) and "__auto_pk" in obj_attr[k]:
                obj_attr[k] = cls.attributes[k].get(obj_attr[k]["__auto_pk"])
            elif isinstance(obj_attr[k], list):
                for i, o in enumerate(obj_attr[k]):
                    if isinstance(o, dict) and "__auto_pk" in o:
                        obj_attr[k][i] = o['__auto_model'].get(o["__auto_pk"])
                        
        #log(cls, obj_attr)
        return cls(**obj_attr)