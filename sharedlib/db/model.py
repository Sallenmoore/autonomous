#local modules
from .db import Database
#external modules
from flask import g, current_app

#python modules
import json
import copy
import logging
log = logging.getLogger()

db = Database()

class BaseModel():
    
    def __init__(self, **kwargs):
        self.__base_attrs = []
        self.__base_attrs = list(vars(self).keys())
        self.pk = int
        self.model_attr()
        self.update(**kwargs)

    def __str__(self):
        text = "{\n"
        for k,v in vars(self).items():
            text += f"\t{k} => {v}\n"
        text += "}"
        return text

    @property
    def _attributes(self):
        #log.debug(f'attributes: {vars(self)}')
        result = {}
        for k,v in vars(self).items():
            #log.debug(f'k: {k} base attr: {self.__base_attrs}')
            if k not in self.__base_attrs:
                result[k] = v
        #log.debug(f'base: {self.__base_attrs}')
        #log.debug(f'attributes: {result}')
        return result

    def update(self, **kwargs):

        self.validate(**kwargs)
        
        #log.debug(f"kwargs: {kwargs}")
        for k, v in kwargs.items():
            if hasattr(self, k):
                #log.info(f"k, v: {k}, {v}")
                #model attributes are set to their type
                setattr(self, k, v)
            else:
                log.debug(f"{k} Not Found")

    def model_attr(self, **kwargs):
        """
        #must overwrite
        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("set model attrs")
    
    def validate(self, **kwargs):
        return True

    def serialize(self):
        """
        
        """
        #log.debug(f'attributes: {vars(self)}')
        #log.debug(f'attributes: {self._attributes}')
        filtered_attrs = {k:v for k,v in self._attributes.items() if v is not None}
        json_data= {}
        for key, value in filtered_attrs.items():
            if hasattr(value, 'serialize') and callable(value.serialize):
                json_data[key] = value.serialize()
            else:
                try:
                    #log.debug(f"{key} : {value}")
                    json.dumps(value)
                except TypeError as e:
                    log.info(f"{e} -- {key} nonserializable")
                else:
                    json_data[key] = value
        return json_data

    @classmethod
    def deserialize(cls, **kwargs):
        return cls(**kwargs)

    def __EQ__(self, other):
        return self.pk == other.pk

class Model(BaseModel):

    def __init__(self, **kwargs):

        #These should not be stored in the db
        self.table_name = type(self).__name__
        self.table = db.get_table(self.table_name)
        super().__init__(**kwargs)

    def validate(self, **kwargs):
        if not kwargs:
            kwargs = self._attributes
        #log.debug(f'{kwargs}')
        for k,v in kwargs.items():
            if getattr(self, k) != v and getattr(self, k) != type(v):
                raise TypeError(f"type mismatch for {k}: expected {getattr(self, k)}, got: {type(v)}")
        return True

    def save(self):
        """
        save() :save object to db
        """
        #log.debug(f'saving...')
        if self.validate():
            obj_serialize = self.serialize()
            #log.debug(f'{obj_serialize}')
            self.pk = self.table.update(obj_serialize)
            #log.debug(f'{obj_serialize}')
            return self.pk
        else:
            log.debug('VERIFICATION FAILED: not saved')
        return None

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