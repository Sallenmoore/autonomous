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
    
    """
    basic model functionality used as a base class for specific model types

    Notes: 
     - model_attr: must return a dictionary of attributes and their types
        - pk: defaults to int, set type if you want to use another data type
     - validate: model must validate attributes against model_attr() abstract method
       - if the attribute is not in model_attr(), it is invalid
       - if the attribute is in model_attr(), but the value is not of the correct type and it cannot be casted to the correct type, it is invalid
       - if the attribute is in model_attr(), but the value is None, it is valid. This is useful for optional attributes and duplicating records by setting the pk to None
    """
    
    def __init__(self, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        self.__base_attrs = []
        self.__base_attrs = list(vars(self).keys())

        self.update(**kwargs)

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        text = "{\n"
        for k,v in vars(self).items():
            text += f"\t{k} => {v} ({type(v)})\n"
        text += "}"
        return text

    def __setattr__(self, name, value):
        attrs = self._model_attrs()
        if value is not None and name in attrs:
            log.debug(f"{name} type {type(value)}, should be {type(value)}")
            # cast it, ex. str -> int: 
            # attr = type(attr)
            value = attrs[name](value)
            log.debug(f"{name} type cast to {type(value)}")
            
        self.__dict__[name] = value
    
############################## Private Methods #####################################
    def _model_attrs(self):
        """
        private proxy method to allow hooks fro pulling attribute types
        adds 'pk' to model_attr()

        Returns:
            _type_: _description_
        """
        attrs = self.model_attr()
        attrs['pk'] = attrs.get('pk', int)
        return attrs

############################## Public Methods #####################################
    def update(self, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        log.debug(f"kwargs: {kwargs}")

        attrs = self._model_attrs()
        
        if self.validate(**kwargs):
            for k,v in kwargs.items():
                setattr(self, k, v)

        log.debug(f"{self}")
    
    def validate(self, **kwargs):
        """
        only validate values being updated

        Raises:
            ValueError: if the value being updated doesn't match type

        Returns:
            bool: whether or not the updates to the object validate
        """
        if not kwargs:
            kwargs = self._attributes

        log.debug(f'{kwargs}')

        attrs = self._model_attrs()
        
        for k,v in kwargs.items():
            if k not in attrs:
                raise Exception(f"Invalid Attribute: {k}")
        log.debug(f'{kwargs}')
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
                    log.debug(f"{e} -- {key} nonserializable")
                else:
                    json_data[key] = value
        return json_data

    ############################## Private Properties       #####################################
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

    ############################## Operators       #####################################
    def __EQ__(self, other):
        return self.pk == other.pk
    
    ############################## Abstract Methods #####################################
    def model_attr(self, **kwargs):
        """
        must overwrite
        pk defaults to int, set an explicit type 
        if you are going to use another value as the pk
        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("set model attrs")

    ############################## Class Methods ########################################
    

    @classmethod
    def deserialize(cls, **kwargs):
        return cls(**kwargs)

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