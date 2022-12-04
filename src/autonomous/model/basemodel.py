#local modules
from autonomous.db.db import Database
from autonomous import log
#python modules
import json
import importlib
import inspect
import pprint

class AutoModel:
    
    def __init__(self, model):
        #log(self.__class__)
        """
        _summary_

        args:
            - attributes: a dict of attributes and their types

        Raises:
            Exception: _description_
        """
        #log(f"Auto modeling", model)
        if not isinstance(model, AutoModel): 
            model.save()
            self._auto_model = model._auto_model
            self._auto_pk = model._auto_pk
        else:
            self.__dict__.update(model.__dict__)
        #breakpoint()
        self._auto_real_obj = None

    def __repr__(self):
        return f"AutoModel({self._auto_model}, {self._auto_pk})"
    
    def __set_name__(self, owner, name):
        log(name)
        self._auto_name = '_' + name
        
    def __get__(self, instance, owner):
        setattr(owner, self._auto_name, self._auto_obj)
        #log(f"Un-Auto modeling")
        return self._auto_obj

    def __set__(self, owner, value):
        #log(self._auto_name)
        #log(f"Un-Auto modeling")
        setattr(owner, self._auto_name, value)

    def __delete__(self, instance):
        model = self._auto_obj
        model.delete()
        del instance

    def __getattr__(self, key):
        #breakpoint()
        if key == "_auto_obj":
            if not self._auto_real_obj:
                self._auto_real_obj = BaseModel.model_loader(self._auto_model).get(self._auto_pk) 
            return self._auto_real_obj
        return getattr(self._auto_obj, key)
    
    def __setattr__(self, key, value):
        #log(self.__class__)
        if key.startswith("__") or key.startswith("_auto_"):
            super().__setattr__(key, value)
        else:
            model = self._auto_obj
            setattr(model, key, value)

    def __delattr__(self, key):
        model = self._auto_obj
        model.__delattr__(key)
        
class BaseModel:
    _auto_attributes = {"_auto_pk":int, "_auto_model":str}
    _auto_models = {}
        
    def __repr__(self):
        return pprint.pformat({**self.__dict__, "_auto_attributes":self._auto_attributes, "Class name":self.__class__}, indent=4, compact=False)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        if 'autonomous' not in str(cls):
            BaseModel._auto_models[cls.__name__] = cls

    ############################## Public Methods #####################################
        
    def update(self, **updates):
        """
        _summary_

        """
        for k,v in updates.items():
            #log(f"{k}  {v}")
            setattr(self, k, v)
    
    ##############################  Properties       #####################################

    @property
    def pk(self):
        return getattr(self, '_auto_pk', None)

    @pk.setter
    def pk(self, value):
        self._auto_pk = value

    ##############################   auto object methods   ########################################

    @classmethod
    def model_loader(cls, name):
        """
        _summary_

        _extended_summary_

        Args:
            name (_type_): _description_

        Returns:
            _type_: _description_
        """
        #log(name, BaseModel._auto_models)
        return BaseModel._auto_models.get(name)

    @classmethod
    def is_auto(cls, name):
        """
        _summary_

        _extended_summary_

        Args:
            name (_type_): _description_

        Returns:
            _type_: _description_
        """
        if hasattr(name, '__class__'):
             name = name.__class__.__name__
        else:
            raise Exception("Unknown type")
        return name in BaseModel._auto_models or name == "AutoModel"

    
    def _proxy_auto_models(self):
        """
        _summary_

        _extended_summary_

        Args:
            val (_type_): _description_
        """
        #log(self.autoattributes)
        def aux_proxy_auto_models(val):
            if BaseModel.is_auto(val):
                #log(val.autoattributes)
                val = AutoModel(val)
            elif isinstance(val, list):
                for i, v in enumerate(val): 
                    val[i] = aux_proxy_auto_models(v)
            elif isinstance(val, dict):
                for k, v in val.items(): 
                    val[k] = aux_proxy_auto_models(v)
            return val
        
        for k, v in self.__dict__.items():
            #log(k, v, type(v))
            self.__dict__[k] = aux_proxy_auto_models(v)
        #log(self.autoattributes)
        return self



    
    # @classmethod
    # def _load_auto_model(cls, attr):
    #     """
    #     _summary_

    #     _extended_summary_

    #     Returns:
    #         _type_: _description_
    #     """
    #     if isinstance(attr, AutoModel):
    #         model = BaseModel.model_loader(attr["_auto_model"])
    #         attr = model(**attr)
    #     elif isinstance(attr, list):
    #         for i, v in enumerate(attr):
    #             attr[i] = BaseModel._load_auto_model(v)
    #     elif isinstance(attr, dict): # and not '_auto_proxy' in attr:
    #         for k, v in attr.items():
    #             attr[k] = cls._load_auto_model(v)
    #     return attr
