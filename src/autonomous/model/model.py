#local modules
from ..db import Database
from .basemodel import BaseModel
from autonomous.logger import log

db = Database()

class Model(BaseModel):

    _attributes = {"pk":int, "model_class":str, "attributes":dict}
    
    def __init__(self, **kwargs):
        #initializes the table
        rec = self.table().get(kwargs.get('pk'))
        log(f"rec:{rec}")
        if rec:
            self.__dict__.update(rec.__dict__)
            
        # update remaining attributes
        for k,v in kwargs.items():
            try:
                kwargs[k] = self.__class__.attributes[k](v)
                log(kwargs[k])
            except Exception as e:
                log(f"{e} -- attribute/value invalid: {k}=>{v}", LEVEL="INFO")
        
        self.__dict__.update(kwargs)
        log(self.__dict__)

    def save(self):
        """
        save() :save object to db
        """
        #log(self.name, self.dndbeyond_id, hasattr(self, "pk"))
        self.pk = self.__class__.table().update(self)
        return self.pk

    def delete(self):
        self.__class__.table().delete(self.pk)

    ################## class methods ####################
    @classmethod
    def table(cls):
        if not hasattr(cls, "_table") or not cls._table:
            cls.model_class = cls.__name__
            cls._table = db.get_table(cls.model_class)
            try:
                cls.attributes.update(Model._attributes)
            except AttributeError:
                log("""
                    Models must have a class variable called 'attributes' that is a dict in the form:
                    attributes = {"attribute_name":attribute_type}
                """)
                raise
        return cls._table
    
    @classmethod
    def all(cls):
        objects = cls.table().all()
        return objects
    
    @classmethod
    def search(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        #log(f"kwargs: {kwargs}")
        return cls.table().search(**kwargs)

    @classmethod
    def get(cls, doc_id=None, pk=None):
        """
        get - 
        params: pk
        return: Always returns single objecrt
        """
        pk = pk or doc_id
        #log(f"obj: {self}")
        data = cls.table().get(pk)
        #log(f"obj: {data}")
        return data