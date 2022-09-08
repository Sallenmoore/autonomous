#local modules
from ..db import Database
from .basemodel import BaseModel

#external modules
#from flask import g, current_app

#python modules
#import json
#import copy

import logging
log = logging.getLogger()

db = Database()

class Model(BaseModel):

    def __init__(self, **kwargs):
        #These should not be stored in the db
        self._table_name = type(self).__name__
        self._table = db.get_table(self._table_name)
        log.warn(f"{kwargs}")
        super().__init__(**kwargs)

    def save(self):
        """
        save() :save object to db
        """
        log.debug(self.attributes)

        obj_serialize = {}
        for k,v in self.serialize().items():
            if self.validate(k,v):
                obj_serialize[k] = v
            else:
                log.debug(f'{k}{v} attribute ignored')

        self.pk = self._table.update(obj_serialize)

        log.debug(f'{self}')

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
        json_objects = cls()._table.search(**kwargs)
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
        #log.debug(f'{kwargs}, {json_object}')
        return cls(**json_object) if json_object else None