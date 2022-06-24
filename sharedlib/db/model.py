#local modules
from .db import Database
#external modules
from flask import g, current_app

#python modules
import json

import logging
log = logging.getLogger()

db = Database()

class BaseModel():
    
    def __init__(self, **kwargs):
        self.pk = None

        self.base_attrs = vars(self)
        self.model_attr()
        self.update()

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
        """
        
        """
        raw_data = vars(self)
        json_data= {}
        for key, value in raw_data.items():
            if value and hasattr(value, 'serialize') and callable(value.serialize):
                json_data[key] = value.serialize()
            else:
                try:
                    #log.debug(f"{key} : {value}")
                    json.dumps(value)
                except Exception as e:
                    log.info(f"{e} -- {key} nonserializable")
                else:
                    json_data[key] = value
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

    @classmethod
    def deserialize(cls, **kwargs):
        return cls(**kwargs)

    def __EQ__(self, other):
        return self.pk == other.pk

class Model(BaseModel):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.table_name = type(self).__name__
        self.table = db.get_table(self.table_name)

    def delete(self):
        self.table.delete(self.pk)

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

