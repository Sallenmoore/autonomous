#local modules
from .db import Database
#external modules
from flask import g, current_app

#python modules
import json
import copy
import logging
import inspect
log = logging.getLogger()

db = Database()

class Model():
    
    def __init__(self, **kwargs):
        """
        _summary_

        _extended_summary_
        """

        #data that will not be serialized
        self.table_name = type(self).__name__
        self.table = db.get_table(self.table_name)
        
        self.__base_attrs = list(vars(self).keys())

        #data that will be serialized
        self.pk = int
        self.model_attr()
        self.update(**kwargs)

    def __str__(self):
        text = "{\n"
        for k,v in vars(self).items():
            text += f"\t{k} => {v}\n"
        text += "}"
        return text

    def model_attr(self):
        """
        #must overwrite
        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("set model attrs")
    
    def verify(self):
        return isinstance(self.pk, int)

    def serialize(self):
        raw_data = vars(self)
        #log.debug(f"raw data : {raw_data}")
        json_data= {}
        for key, value in raw_data.items():
            if key != "base_attrs" and key not in self.__base_attrs:
                #log.info(f"serializing : {key}, {value}")
                if hasattr(value, 'serialize'):
                    json_data[key] = value.serialize()
                elif callable(value):
                    json_data[key] = value()
                else:
                    try:
                        #log.info(f"{key} : {value}")
                        json_data[key]= json.dumps(value)
                    except Exception as e:
                        json_data[key] = f"{value} not serializable"
        #log.debug(f"json_data : {json_data}")
        return json_data 

    #template_method
    def save(self):
        """
        save() :save object to db
        """
        if self.verify():
            obj_serialize = self.serialize()
            #log.debug(f'{obj_serialize}')
            self.pk = self.table.update(obj_serialize)
        

    def __EQ__(self, other):
        return self.pk == other.pk

    def delete(self):
        self.table.delete(self.pk)

    def update(self, **kwargs):
        log.debug(f"kwargs: {kwargs}")
        for k, v in kwargs.items():
            if hasattr(self, k):
                #log.info(f"k, v: {k}, {v}")
                #model attributes are set to their type
                if k not in self.__base_attrs and getattr(self, k) != type(v):
                    log.warning(f"type mismatch for {k}: expected {getattr(self, k)}, got: {type(v)}")
                setattr(self, k, v)
            else:
                log.info(f"{k} Not Found")
        return self.verify()
                
    ################## class methods ####################
    @classmethod
    def all(cls):
        objects = cls().table.all()
        return [cls(**objs) for objs in objects]
    
    @classmethod
    def find(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        json_objects = cls().table.search(**kwargs)
        return [cls(**o) for o in json_objects]

    @classmethod
    def get(cls, doc_id=None, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objectr
        """
        pk = int(pk or doc_id)
        json_object = cls().table.get(pk)
        #log.debug(f'{kwargs}, {json_object}')
        return cls(**json_object) if json_object else None

