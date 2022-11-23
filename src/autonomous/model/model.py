#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous.logger import log

import jsonpickle

import inspect, os

db = Database()

class Model(BaseModel):

    _attributes = {"pk":int, "_auto_model":str, "attributes":dict}
    _type_defaults = {
        str: "",
        list: [],
        dict: {},
    }
    
    def __init__(self, **kwargs):
        # set attributes to default values
        #log(f"updated values:{kwargs}")
        self.pk = kwargs.get('pk')
        rec = self.__class__._table().get(self.pk)
        model = {k:self._decode(k, v) for k,v in rec.items()} if rec else {}

        for k,v in self.__class__.attributes.items():
            #log(self.__class__.__name__,self.attributes, LEVEL="INFO")
            if k in kwargs:
                #log(f"updated value:{kwargs[k]}", LEVEL="INFO")
                setattr(self, k, kwargs[k])
            elif k in model:
                #log(f"stored value:{model[k]}", LEVEL="INFO")
                setattr(self, k, model[k])
            elif k not in Model._attributes:
                #log("default", LEVEL="DEBUG")
                setattr(self, k, self._type_defaults.get(v))

        self.attributes = self.__class__.attributes
        self._auto_model = self.__class__._auto_model
        self.validate()
        #log(self.__class__.__name__,self, LEVEL="DEBUG")
        assert self.attributes

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
        #log(name, attr)
        if BaseModel.is_auto_model(attr):
            #log(f"{self.attributes}", LEVEL="INFO")
            model = self.attributes[name].get(attr["_auto_pk"])
            if "_auto_updates" in attr:
                model.update(**attr["_auto_updates"])
            setattr(self, name, model)
            attr = model
        elif isinstance(attr, list):
            for i, v in enumerate(attr):
                if BaseModel.is_auto_model(v):
                    model_class = self.model_loader(v['_auto_model'])
                    
                    #log(v['_auto_model'], model_class.__name__)

                    model = model_class.get(v["_auto_pk"])
                    model.update(**v.get("_auto_updates", {}))
                    attr[i] = model
        return attr
    
    def save(self):
        """
        save(): save object to db
        """
        #log(self)
        #save any submodels
        for key, val in self.__dict__.items():
            #log(type(val), isinstance(val, Model))
            if isinstance(val, Model):
                val.save()
            elif isinstance(val, list):
                for i, v in enumerate(val):
                    if isinstance(v, Model):
                        v.save()

        log(self, LEVEL="DEBUG")
        serialized_obj = self.serialize()
        log(serialized_obj, LEVEL="DEBUG")
        self.pk = self._table().update(serialized_obj)
        log(self, LEVEL="DEBUG")
        return self.pk

    def delete(self, keep_related=False):
        if not keep_related:
            for k,v in self.__dict__.items():
                if isinstance(v, Model):
                    v.delete()
        self._table().delete(self.pk)

    def update(self, **updates):
        for k,v in updates.items():
            log(f"{k}  {self.attributes}", LEVEL="DEBUG")
            if k in self.attributes:
                log(f"Updating {k}: {getattr(self, k)} => {v}", LEVEL="DEBUG")
                setattr(self, k, v)
                log(f"Updated {k}: {getattr(self, k)}", LEVEL="DEBUG")
            
    
    ################## class methods ####################
    @classmethod
    def _table(cls):
        log(cls, LEVEL="DEBUG")
        if not getattr(cls, "__table", None):
            cls._auto_model = cls.__name__
            cls.__table = db.get_table(cls._auto_model)
            cls.attributes.update(Model._attributes)
            log(cls.__table,cls.attributes, LEVEL="DEBUG")
        return cls.__table
    
    @classmethod
    def all(cls):
        return cls.deserialize_list(cls._table().all())
    
    @classmethod
    def search(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        #log(f"kwargs: {kwargs}")
        results = cls._table().search(**kwargs)
        return cls.deserialize_list(results)

    @classmethod
    def get(cls, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        log(LEVEL="DEBUG")
        
        if not pk: return None
        
        log(f"pk: {pk}", LEVEL="DEBUG")
        
        data = cls._table().get(pk)
        
        log(f"data: {data}", LEVEL="DEBUG")
        
        obj = cls.deserialize(data)
        
        log(f"obj: {obj}", LEVEL="DEBUG")
        
        return obj
        

                
    @classmethod
    def delete_all(cls):
        cls._table().clear()
    ############################## Serialization ########################################
    def validate(self):
        for k,v in self.__dict__.items():
            # valid attribute - verify value is valid
            if v and k in self.__class__.attributes:
                #check if it is a model object
                if issubclass(self.__class__.attributes[k], Model):
                    assert isinstance(v, Model) or "_auto_pk" in v
                elif self.__class__.attributes[k] != type(v):
                    try:
                        setattr(self, k, self.__class__.attributes[k](v))
                    except Exception as e:
                        log(f"type not equal k:{k} v:{v}", e, LEVEL="DEBUG")

    def serialize(self):
        #log(LEVEL="INFO")
        """
        
        """
        #log(self)
        self.validate()
        
        obj_dict = {}
        for k,v in self.__class__.attributes.items():

            #log(f" {k}:{getattr(self, k)}")

            obj_dict[k] = self._encode(k, getattr(self, k))

            #log(f" {k}:{obj_dict[k]}")
        return obj_dict
    
    @classmethod
    def deserialize_list(cls, pickled_objs, **kwargs):
        return [cls.deserialize(obj, **kwargs) for obj in pickled_objs if obj]

    @classmethod
    def deserialize(cls, pickled_obj, **kwargs):
        #log(pickled_obj)
        """
        _summary_

        _extended_summary_
        """

        if not pickled_obj:
            return None
        #log(cls, pickled_obj)
        obj_attr = {}
        for k,v in pickled_obj.items():
            obj_attr[k] = cls._decode(k, v)
        #log(cls, obj_attr)
        return cls(**obj_attr)

    @classmethod
    def _decode(cls, k, v, **kwargs):
        """

        _extended_summary_
        """

        try:
            attr = jsonpickle.decode(v, **kwargs)
        except Exception as e:
            log(f"[ {e} ] cannot decode data -- {v}", LEVEL="DEBUG")
            return

        return attr

    @classmethod
    def _encode(cls, k, v, **kwargs):
        """

        _extended_summary_
        """

        if isinstance(v, Model):
            v = {"_auto_pk":v.pk, "_auto_model":v.__class__.__name__}
        elif isinstance(v, list):
            for i, o in enumerate(v):
                if isinstance(o, Model):
                    v[i] = {"_auto_pk":o.pk, "_auto_model":o.__class__.__name__}

        return jsonpickle.encode(v, **kwargs)