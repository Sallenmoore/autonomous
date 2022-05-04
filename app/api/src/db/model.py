#local modules
from src.db.db import Database
#external modules
from flask import g, current_app

#python modules
import json
import uuid
import logging

log = logging.getLogger()

db = Database()

class Model():
    
    def __init__(self, **kwargs):
        self._id = kwargs.get("pk")
        self.table_name = type(self).__name__
        self.table = db.get_table(self.table_name)
        
        self.model_attr()
        for k, v in kwargs.items():
            if hasattr(self, k):
                #model attributes are set to their type
                v = getattr(self, k)(v)
                setattr(self, k, v)
            else:
                print("Not Found")

    def model_attr(self):
        """
        #must overwrite
        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("set model attrs")
    
    def verify(self):
        """
        #must overwrite

        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("verify values before save")

    def serialize(self):
        raw_data = vars(self)
        json_data= {"pk" : self._id}
        for key, value in raw_data.items():
            if hasattr(value, 'serialize'):
                json_data[key] = value.serialize()
            else:
                try:
                    json_data[key] = json.dumps(value)
                except Exception as e:
                    log.exception(f"ERROR: {e} {key} nonserializable")
        
        return json_data

    #template_method
    def save(self):
        """
        save() :save object to db
        """
        if self.verify():
            self._id = self.table.update(self.serialize())
        

    def __EQ__(self, other):
        return self._id == other._id

    def delete(self):
        self.table.remove(self._id)

    ################## class methods ####################
    @classmethod
    def deserialize(cls, **kwargs):
        return cls(**kwargs)
                
    @classmethod
    def all(cls):
        objects = cls().table.all()
        return [cls(pk=pk, **attrs) for pk, attrs in objects.items()]
    
    @classmethod
    def find(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        json_objects = cls().table.search(**kwargs)
        return [cls(o) for o in json_objects]


