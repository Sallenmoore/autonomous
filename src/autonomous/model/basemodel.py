#local modules
from autonomous.db.db import Database
from autonomous import log
#python modules
import json
import importlib
import inspect
import pprint

# TODO: make abstract with abc module

class BaseModel():
    _auto_attributes = {"_auto_pk":int, "_auto_model":str}
    _auto_models = {}

    def __init__(self):
        self._auto_pk = None
        self._auto_model = self.__class__.__name__
        self.__class__._auto_attributes.update(self.__class__.auto_attributes())
        #log(self.__class__, self.__class__._auto_attributes)
        
    def __repr__(self):
        return pprint.pformat(self.__dict__, indent=4, compact=False)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        if 'autonomous' not in str(cls):
            cls._auto_model = cls.__name__
            cls._auto_pk = None
            BaseModel._auto_models[cls.__name__] = cls

    def __getattribute__(self, name):
        """
        _summary_

        _extended_summary_

        Args:
            name (str): _description_

        Returns:
            _type_: _description_
        """
        attr = super().__getattribute__(name)
        #log(name, type(attr), attr)
        if not inspect.ismethod(attr) and not name.startswith("__") and not name.startswith("_auto"):
            attr = BaseModel._load_auto_model(attr)
            setattr(self, name, attr)
        #log(name, type(attr), attr)
        return attr

    ############################## Public Methods #####################################
    # def auto_attributes(self):
    #     log(self.__class__._auto_attributes)
    #     return self.__class__._auto_attributes
        
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

    def _get_auto_proxy(self):
        self._auto_pk = self.save()
        result = {"_auto_pk":self._auto_pk, "_auto_model":self._auto_model}
        log(result)

    def _proxy_auto_models(self):
        """
        _summary_

        _extended_summary_

        Args:
            val (_type_): _description_
        """
        
        def aux_proxy_auto_models(val):
            if isinstance(val, dict):
                if '_auto_model' in val:
                    val = val._get_auto_proxy()
                else:
                    for k, v in val.items():
                        val[k] = aux_proxy_auto_models(v) 
            elif isinstance(val, list):
                for i, v in enumerate(val): 
                    val[i] = aux_proxy_auto_models(v) 
            return val
        
        for k, v in self.__dict__.items():
            #log(k, v, type(v))
            self.__dict__[k] = aux_proxy_auto_models(v)
    
    @classmethod
    def _load_auto_model(cls, attr):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        if isinstance(attr, dict) and '_auto_model' in attr:
            model = BaseModel.model_loader(attr["_auto_model"])
            attr = model(**attr)
        elif isinstance(attr, list):
            for i, v in enumerate(attr):
                attr[i] = BaseModel._load_auto_model(v)
        elif isinstance(attr, dict): # and not '_auto_proxy' in attr:
            for k, v in attr.items():
                attr[k] = cls._load_auto_model(v)
        return attr
