#local modules
from ..db import Database
from .basemodel import BaseModel, AutoModel
from autonomous import log

## routing modules
from autonomous.handler import NetworkHandler
from flask import request

import inspect, os

db = Database()

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
        
        #log(BaseModel._auto_models)
        self._auto_pk = None
        self._auto_model = self.__class__.__name__
        #log(self.__class__, self, self._auto_model, self._auto_pk, self._auto_attributes, kwargs)
        #log(self.autoattributes)
        self._auto_attributes = {**self.autoattributes(), **self._auto_attributes}
        #log(self.autoattributes)
        if rec := self._table().get(kwargs.get('_auto_pk')):
            #log(self.__class__, self._auto_attributes)
            self.__dict__.update(**rec)
        #log(self.__class__, self._auto_attributes)
        for k, v in kwargs.items():
            setattr(self, k, v)
        #log(self.autoattributes)
            
    def __setattr__(self, k, v):
        #log(self)
        if k == 'pk': k = '_auto_pk'

        if k == '_auto_attributes':
            #log(k, v, self._auto_attributes)
            self.__dict__[k] = v
            #log(k, v, self._auto_attributes)
            return
        
        if k in self._auto_attributes:
            if BaseModel.is_auto(v):
                #log(k, v.autoattributes) 
                v = AutoModel(v)
            self.verify_types(k, v)
            #log(k, v, self.autoattributes)
            self.__dict__[k] = v
        else:
            log(f"Invalid attribute {k} for {self.__class__.__name__}. Must be one of", self._auto_attributes)
        #log(self)
            
    def autoattributes(self):
        #log(self.autoattributes)
        raise NotImplementedError("Must be implemented by Models")

    def verify_types(self, k, v):
        if not v: return True
        if BaseModel.is_auto(v):
            #breakpoint()
            if BaseModel.model_loader(v._auto_model) != self._auto_attributes[k]:
                log(f"WARNING: INVALID MODEL ATTRIBUTE TYPE => {k} : {v} [{type(v)}!={self._auto_attributes[k]}]")
                raise TypeError(f"WARNING: INVALID AUTOMODEL => {k} : {v} [{type(v)}!={self._auto_attributes[k]}]")
            return True
        else:
            if self._auto_attributes[k] != type(v):
                try:
                    self._auto_attributes[k](v)
                except Exception as e:
                    log(f"[{e}]", f"WARNING: INVALID MODEL ATTRIBUTE TYPE => {k} : [{self._auto_attributes[k]}!={type(v)}]")
                return True
                

    ################## db methods ####################
    @classmethod
    def _table(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        try:
            return cls.__table
        except AttributeError:
            cls.__table = db.get_table(cls.__name__)
            return cls.__table
    
    @classmethod
    def get(cls, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        
        if not pk: return None
        
        #log(f"pk: {pk}", type(pk))
        
        data = cls._table().get(pk)
        
        #log(f"cls: {cls}", cls._auto_attributes, data)
        
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
        results = [cls(**item) for item in cls._table().all()]
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
        self._proxy_auto_models()

        self.pk = self._table().update(self)

        #log("="*100, "\n\n\nleft off here -  everything seems good after save in make_model()\n\n\n===", "="*100)
        #breakpoint()
        return self.pk
    
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
                    
        self._table().delete(self.pk)

    @classmethod
    def delete_all(cls):
        return cls._table().clear()

    ############## routing methods ##############

    @classmethod
    def crud(cls, app):
        from functools import partial
        log(cls)
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
        log(cls, pk)
        mt = cls.get(pk)
        
        return NetworkHandler.package(mt)

    @classmethod
    def __route_search(cls):
        model_objs = cls.search(**request.values)
        return NetworkHandler.package(model_objs)

    @classmethod
    def __route_all(cls):
        mt = cls.all()
        return NetworkHandler.package(mt)

    @classmethod
    def __route_upsert(cls):
        #log(f"request.json: {request.json}")
        model_objs = NetworkHandler.unpackage(request.json)
        for i, mo in enumerate(model_objs):
            
            model = BaseModel.model_loader(mo._auto_model)
            if mt := mo.get("_auto_pk"):
                mt.update(**mo)
            else:
                mt = cls(**mo)
                
            if not mt.save():
                model_objs[i] = f"{mt._auto_model} could not be saved. Unknown error."
            else:
                model_objs[i] = mt
                
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