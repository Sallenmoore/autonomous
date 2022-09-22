#local modules
from sharedlib.db.db import Database
from sharedlib.logger import log
#external modules
from flask import g, current_app

#python modules
import json
import copy

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

        if not hasattr(self.__class__, "attributes"):
            #log(f"getting attributes for {self.__class__.__name__}")
            self.__class__.attributes = self.model_attr()
            self.__class__.attributes['pk'] = self.__class__.attributes.get('pk', int)
            self.__class__.attributes['model_class'] = str
        #log(kwargs)
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
            
        if name != "attributes" and value != None and name in self.attributes:
            # cast it, ex. str -> int: 
            # attr = type(attr)
            #log(f"casting {name}:{value} to {self.attributes[name]}")
            value = self.attributes[name](value)
        #log(f"setting {name} to {value}")
        self.__dict__[name] = value

############################## Public Methods #####################################
    def update(self, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        
        if kwargs:
            for k,v in kwargs.items():
                if self.validate(k, v):
                    setattr(self, k, v)
    
    def validate(self, key, value):
        """
        Placeholder for future validation
        """
        return True
    
    def serialize(self):
        """
        
        """
        filtered_attrs = {k:v for k,v in self.attributes.items() if v is not None}
        json_data= {}
        for key in filtered_attrs.keys():

            # verify the attribute is valid
            try:
                attr = getattr(self, key)
            except AttributeError as e:
                continue

            # check if object has serialize()
            try:
                json_data[key] = attr.serialize()  
            except AttributeError as e:
                log(f"{e} -- {key} is an invalid attribute", "DEBUG")
            else:
                continue

            # check if object is serializable
            try:
                json.dumps(attr)
            except TypeError as e:
                log(f"{e} -- {key} nonserializable", "DEBUG")
            else:
                json_data[key] = attr
        return json_data

    ##############################  Properties       #####################################


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
    def deserialize(cls, results):
        objects = []
        for r in results:

            o = cls(**r)

            objects.append(o)
        return objects
