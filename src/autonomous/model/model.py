#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous import log

## routing modules
from autonomous import response
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
        super().__init__()
        
        if rec := self._table().get(kwargs.get('_auto_pk')):
            self.update(**rec)
        #log(rec, self)
        self.update(**kwargs)
        #log(kwargs, self)

    ################## db methods ####################
    @classmethod
    def _table(cls):
        
        #log(cls)
        if not getattr(cls, "__table", None):
            cls.__table = db.get_table(cls._auto_model)
            #log(cls.__table,cls.attributes)
            
        return cls.__table
    
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
        #log(self.pk, self)
        return self.pk

    def update(self, **updates):
        """
        _summary_

        """
        filtered_attribs = {}
        #log(self.auto_attributes(), self._auto_attributes)
        for k,t in self._auto_attributes.items():
            #log(self.__class__, f"{self._auto_model}::{k}: {t}")
            if updates.get(k):
                #log(self.__class__, f"updating {k} => {updates[k]}")
                if t != type(updates[k]):
                    try:
                        filtered_attribs[k] = t(updates[k])
                    except Exception as e:
                        log(f"Error [{e}]", f"INVALID MODEL ATTRIBUTE => {k} : {updates[k]} [{type(updates[k])}!={t}]")
                else:
                    filtered_attribs[k] = updates[k]
            elif not getattr(self, k, None):
                #log(self.__class__, f"default:{self._auto_type_defaults.get(k)}")
                filtered_attribs[k] = self.__class__._auto_type_defaults.get(t)
        #log(self.__class__, f"filtered:{filtered_attribs}")
        super().update(**filtered_attribs)
        #log(filtered_attribs=filtered_attribs)

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        results = []
        for item in cls._table().all():
            result = cls(**item)
        return 
    
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
    def get(cls, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        
        if not pk: return None
        
        #log(f"pk: {pk}")
        
        data = cls._table().get(pk)
        
        #log(f"obj: {obj}", type(data))
        
        return cls(**data)
    
    def delete(self, keep_related=False):
        """
        _summary_

        _extended_summary_

        Args:
            keep_related (bool, optional): _description_. Defaults to False.
        """
        if not keep_related:
            for k,v in self.__dict__:
                if isinstance(getattr(self, k), BaseModel):
                    v.delete()
        self._table().delete(self.pk)

    @classmethod
    def delete_all(cls):
        cls._table().clear()

    ############## routing methods ##############

    @classmethod
    def crud(cls, app):
        
        #app.add_url_rule(rule, endpoint="get", view_func=Model.modelget, methods=('GET',))
        app.add_url_rule(f'{route}/<int:pk>', endpoint="get", view_func=Model.modelget, methods=('GET',))
        app.add_url_rule(f'{route}/all', endpoint="all", view_func=Model.modelall,  methods=('GET',))
        app.add_url_rule(f'{route}/update', endpoint="update", view_func=Model.modelupsert,  methods=('POST',))
        app.add_url_rule(f'{route}/create', endpoint="create", view_func=Model.modelupsert,  methods=('POST',))
        app.add_url_rule(f'{route}/delete', endpoint="delete", view_func=Model.modeldelete,  methods=('POST',))
        app.add_url_rule(f'{route}/search/', endpoint="search", view_func=Model.modelsearch,  methods=('GET','POST'))

    @classmethod
    def modelget(cls, pk):
        mt = cls.get(pk)
        #log(f"modeltestget: {mt}")
        return response.package(mt)
    
    @classmethod
    def modelall(cls):
        mt = cls.all()
        return response.package(mt)

    @classmethod
    def modelsearch(cls):
        model_objs = cls.search(**request.values)
        return response.package(model_objs)

    @classmethod
    def modeldelete(cls):
        pk = response.unpackage(request.json)[0]
        mt = cls.get(pk)
        mt.delete()
        return response.package(mt)
    
    @classmethod
    def modelupsert(cls):
        #log(f"request.json: {request.json}")
        model_objs = response.unpackage(request.json)
        for i, mo in enumerate(model_objs):
            
            #log(f"mo: {mo}")
            if mt := mo.get("_auto_pk"):
                mt.update(**mo)
            else:
                mt = cls(**mo)
                
            if not mt.save():
                model_objs[i] = f"{mt._auto_model} could not be saved. Unknown error."
            else:
                model_objs[i] = mt
                
        return response.package(model_objs)