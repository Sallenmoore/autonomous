#local modules
from ..db import Database
from .basemodel import BaseModel
from self.utilities.logger import log

#external modules
#from flask import g, current_app

#python modules
#import json
#import copy

db = Database()

class Model(BaseModel):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        #These should not be stored in the db
        self._table_name = type(self).__name__
        self._table = db.get_table(self._table_name)
        self.model_class = self._table_name

    def save(self):
        """
        save() :save object to db
        """

        obj_serialize = {}
        for k,v in self.serialize().items():
            if self.validate(k,v):
                obj_serialize[k] = v
            else:
                log(f'{k}{v} attribute ignored', "INFO")

        self.pk = self._table.update(obj_serialize)

        return self.pk

    def delete(self):
        self._table.delete(self.pk)

    ################## class methods ####################
                
    @classmethod
    def all(cls):
        objects = cls()._table.all()
        return [cls(**objs) for objs in objects]
    
    @classmethod
    def find(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        #log(f"kwargs: {kwargs}")
        json_objects = cls()._table.search(**kwargs)
        #log(f"kwargs: {kwargs}")
        # else:
        #     json_objects = cls.all()
        #log(json_objects)
        return [cls(**o) for o in json_objects]

    @classmethod
    def get(cls, doc_id=None, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objectr
        """
        pk = pk or doc_id
        json_object = cls()._table.get(pk)
        return cls(**json_object) if json_object else None