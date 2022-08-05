#local modules
from .db import Database

#python modules
import json
import copy

import logging
log = logging.getLogger()

db = Database()

class Model(BaseModel):

    def __init__(self, **kwargs):

        #These should not be stored in the db
        self.table_name = type(self).__name__
        self.table = db.get_table(self.table_name)
        super().__init__(**kwargs)

    def save(self):
        """
        save() :save object to db
        """
        log.info(self._attributes)
        if self.validate():
            obj_serialize = self.serialize()

            log.debug(f'{obj_serialize}')

            self.pk = self.table.update(obj_serialize)

            log.info(f'{self}')

            return self.pk
        else:
            raise Exception('VERIFICATION FAILED: not saved')

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
        pk = pk or doc_id
        json_object = cls().table.get(pk)
        #log.debug(f'{kwargs}, {json_object}')
        return cls(**json_object) if json_object else None