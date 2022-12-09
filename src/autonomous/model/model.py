#local modules
from ..db.db import auto_db
from .basemodel import BaseModel, AutoModel
from autonomous import log

## routing modules
from autonomous.handler import NetworkHandler
from flask import request

## built-ins
import inspect, os
from functools import partial

## for debugging
import jsonpickle

class Model(BaseModel):

    _auto_type_defaults = {
        str: "",
        list: [],
        dict: {},
    }
    
    def __init__(self, **kwargs):
        """
        _summary_

        _extended_summary_
        """
        self._auto_attributes = self.autoattributes()
        self._auto_attributes.update(BaseModel._base_attributes)
        self._auto_pk = None
        self._auto_model = self.__class__.__name__
        
        
        if rec := self._table().get(kwargs.get('_auto_pk')):
            self.__dict__.update(**rec)
        #breakpoint()
        for k, v in kwargs.items():
            setattr(self, k, v)
        #breakpoint()

        def __repr__(self):
            return pprint.pformat({**self.__dict__, "_auto_attributes":self._auto_attributes, "classname":self.__class__}, indent=4, compact=False)
    
    def __setattr__(self, k, v):
        if k == "_auto_attributes" and isinstance(v, dict):
            self.__dict__[k] = v
        elif k in self._auto_attributes:
            self.__dict__[k] = AutoModel(v) if BaseModel.is_auto(v) else self.verify_type(k, v)
        else:
            raise AttributeError(f"Invalid attribute {k} for {self.__class__.__name__}. Must be one of {self._auto_attributes}")
        

    def autoattributes(self):
        raise NotImplementedError("Must be implemented by Models")

    def verify_type(self, k, v):
        if v != None and self._auto_attributes[k] != type(v): 
            try:
                v = self._auto_attributes[k](v)
            except Exception as e:
                log(f"[{e}]", f"WARNING: INVALID MODEL ATTRIBUTE TYPE => {k} : [{self._auto_attributes[k]}!={type(v)}]")
                raise e
        return v
            

    ################## db methods ####################
    @classmethod
    def _table(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        if "_auto_table" not in cls.__dict__:
            cls._auto_table = auto_db.get_table(cls.__name__)
        #
        return cls._auto_table
    
    @classmethod
    def get(cls, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        
        if not pk: return None
        #breakpoint()
        #log(f"pk: {pk}", type(pk))
        data = cls._table().get(pk)
        
        #log(f"cls: {cls}", cls._auto_attributes, data)
        #breakpoint()
        return cls(**data) if data else None
    
    @classmethod
    def search(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        #log(f"kwargs: {kwargs}")
        results = cls._table().search(**kwargs)
        return [cls(**items) for items in results]

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        #log(cls, cls._table().all())
        results = []
        for item in cls._table().all():
            obj = cls(**item)
            results.append(obj)
        return results

    def save(self):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        #log(self)
        
        #save any submodels
        self.proxy_auto_models()
        #log(self)
        self._auto_pk = self._table().update(self)
        #log(self)
        #log("="*100, "\n\n\nleft off here -  everything seems good after save in make_model()\n\n\n===", "="*100)
        #breakpoint()
        return self._auto_pk
    
    def delete(self, keep_related=False):
        """
        _summary_

        _extended_summary_

        Args:
            keep_related (bool, optional): _description_. Defaults to False.
        """
        if not keep_related:
            for k, v in self.__dict__.items():
                #breakpoint()
                if BaseModel.is_auto(v):
                    v.delete()
                    self.__dict__[k] = self.__class__._auto_type_defaults.get(self._auto_attributes[k])
                    
        self._table().delete(self._auto_pk)

    @classmethod
    def delete_all(cls):
        return cls._table().clear()

    ############## routing methods ##############

    @classmethod
    def crud(cls, app):
        #log(cls)
        route=cls.__name__.lower()
        #app.add_url_rule(rule, endpoint="get", view_func=cls.modelget, methods=('GET',))
        app.add_url_rule(f'/{route}/<int:pk>', endpoint=f"{route}_get", view_func=partial(cls.__route_get), methods=('GET',))
        app.add_url_rule(f'/{route}/all', endpoint=f"{route}_all", view_func=partial(cls.__route_all),  methods=('GET',)) 
        app.add_url_rule(f'/{route}/update', endpoint=f"{route}_update", view_func=partial(cls.__route_upsert),  methods=('POST',))
        app.add_url_rule(f'/{route}/delete', endpoint=f"{route}_delete", view_func=partial(cls.__route_delete),  methods=('POST',))
        app.add_url_rule(f'/{route}/search/', endpoint=f"{route}_search", view_func=partial(cls.__route_search),  methods=('GET','POST'))
        app.add_url_rule(f'/{route}/deleteall', endpoint=f"{route}_deleteall", view_func=partial(cls.__route_delete_all),  methods=('POST',))
        
    @classmethod
    def __route_get(cls, pk):
        #log(cls, pk)
        mt = cls.get(pk)
        
        return NetworkHandler.package(mt)

    @classmethod
    def __route_search(cls):
        model_objs = cls.search(**request.values)
        return NetworkHandler.package(model_objs)

    @classmethod
    def __route_all(cls):
        mt = cls.all()
        log(mt)
        return NetworkHandler.package(mt)

    @classmethod
    def __route_upsert(cls):
        #log(f"request.json: {request.json}")
        model_objs = NetworkHandler.unpackage(request.json)
        for i, mo in enumerate(model_objs):
            log(i, mo)
            if not mo.save():
                model_objs[i] = f"{mo._auto_model} could not be saved. Unknown error."
            else:
                model_objs[i] = mo
                
        return NetworkHandler.package(model_objs)

    @classmethod
    def __route_delete(cls):
        pk = NetworkHandler.unpackage(request.json)[0]
        mt = cls.get(pk)
        mt.delete()
        return NetworkHandler.package(mt)

    @classmethod
    def __route_delete_all(cls):
        log("Here")
        mt = cls.delete_all()
        return NetworkHandler.package(mt)