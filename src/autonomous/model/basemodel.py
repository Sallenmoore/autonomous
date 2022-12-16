#local modules
from autonomous import log
#python modules
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
        self._auto_name = None
        self._auto_real_obj = None
        if BaseModel.model_loader(model.__class__.__name__):
            model.save()
            self._auto_real_obj = model
        elif isinstance(model, dict):
            #log(model)
            model_cls = BaseModel.model_loader(model['_auto_model'])
            self._auto_real_obj = model_cls(**model)
            self._auto_pk = self._auto_real_obj._auto_pk
        elif isinstance(model, AutoModel):
            self._auto_model = model._auto_model
            self._auto_pk = model._auto_pk

        #self._auto_model = model._auto_model

    
    @property
    def _auto_obj(self):
        if not self._auto_real_obj:
            self._auto_real_obj = BaseModel.model_loader(self._auto_model).get(self._auto_pk) 
        return self._auto_real_obj

    # def __setitem__(self, key, item):
    #     setattr(self._auto_obj, key, item)

    # def __getitem__(self, key):
    #     return getattr(self._auto_obj, key)

    def __getstate__(self):
        if self._auto_obj:
            self._auto_pk = self._auto_obj.save()
        return {
            "_auto_name":self._auto_name,
            "_auto_model":self._auto_model,
            "_auto_pk":self._auto_pk
        }

    def __setstate__(self, state):
        #log(state)
        self._auto_name = state.get("_auto_name")
        self._auto_model = state["_auto_model"]
        self._auto_pk = state["_auto_pk"]
        self._auto_real_obj = None

    def __repr__(self):
        return f"AutoModel({self._auto_model}, _auto_pk:{self._auto_pk}, _auto_name:{self._auto_name}, _auto_real_object:{self._auto_real_obj})"
    
    def __set_name__(self, owner, name):
        #log(name)
        self._auto_name = '_' + name

    def __contains__(self, item):
      return item in self._auto_obj
    
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
        result = getattr(self._auto_obj, key)
        return result
    
    def __setattr__(self, key, value):
        #log(self.__class__)
        if key.startswith("__") or key.startswith("_auto_"):
            super().__setattr__(key, value)
        else:
            model = self._auto_obj
            setattr(model, key, value)
            model.save()
 
    def __delattr__(self, key):
        model = self._auto_obj
        model.__delattr__(key)

    # def __getstate__(self):
        
    #     return 

    # def __setstate__(self, state):
    #     self.__dict__.update(state)
        
class BaseModel:
    _base_attributes = {"_auto_pk":int, "_auto_model":str}
    _auto_models = {}
    
    def __repr__(self):
        return pprint.pformat({**self.__dict__}, indent=4, compact=False)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        if 'autonomous' not in str(cls):
            BaseModel._auto_models[cls.__name__] = cls

    # def __getstate__(self):
    #     self.proxy_auto_models()
    #     return self.__dict__

    # def __setstate__(self, state):
    #     log(state)
    #     self.__dict__.update(state)

    def __reduce__(self):
        self.proxy_auto_models()
        return (AutoModel, ({'_auto_model':self._auto_model,"_auto_pk":self._auto_pk, **self.__dict__},))

    def __contains__(self, item):
      return item in self._auto_attributes

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
    def is_auto(cls, obj):
        """
        _summary_

        _extended_summary_

        Args:
            name (_type_): _description_

        Returns:
            _type_: _description_
        """
        return isinstance(obj, (AutoModel, *BaseModel._auto_models.values(),))

    def _proxy_auto_models(self, val):
        if BaseModel.is_auto(val):
            #log(val.autoattributes)
            val = AutoModel(val)
        elif isinstance(val, (list, set)):
            for i, v in enumerate(val): 
                val[i] = self._proxy_auto_models(v)
        elif isinstance(val, dict):
            for k, v in val.items(): 
                val[k] = self._proxy_auto_models(v)
        return val

    def proxy_auto_models(self):
        """
        _summary_

        _extended_summary_

        Args:
            val (_type_): _description_
        """
        #log(self.autoattributes)
        
        for k, v in self.__dict__.items():
            #log(k, v, type(v))
            self.__dict__[k] = self._proxy_auto_models(v)
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
