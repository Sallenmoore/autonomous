#local modules
from src.db.db import Database

#external modules
from flask import g, current_app, jsonify

#python modules
import json
import uuid

db = Database()

class Model():
    
    def __init__(self, **kwargs):
        self._id = kwargs.get("pk")
        self.table_name = str(type(self))
        self.table = db.get_table(self.table_name)
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, v)
            else:
                print(f"Not found: {k}, {v}")

        self.model_attr()

    def model_attr(self):
        """
        #must overwrite
        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("set model attrs")
    
    def verify(self):
        """
        #must overwrite

        Raises:
            NotImplementedError: [description]
        """
        raise NotImplementedError("verify values before save")

    def serialize(self):
        json_data = vars(self)
        json_data["pk"] = self._id
        for key, value in json_data.items():
            if hasattr(value, 'serialize'):
                json_data[key] = value.serialize()
            else:
                try:
                    json_data[key] = json.dumps(value)
                except Exception as e:
                    print(f"ERROR: {e}")
                    json_data[key] = "<nonserializable>"
        return json_data

    def deserialize(self, attrs=None, **data):
        for key in data:
            if not attrs or key in attrs:
                setattr(self, key, data[key])

    #template_method
    def save(self):
        """
        save() :save object to db
        """
        if not self._id:
            self._id = uuid.uuid4()
        if self.verify():
            self.table.update(self.serialize())

    def __EQ__(self, other):
        return self._id == other._id

    def delete(self):
        self.table.remove(self._id)

    ################## class methods ####################
    @classmethod
    def all(cls):
        objects = cls().table.all()
        return [cls(pk=pk, **attrs) for pk, attrs in objects.items()]
    
    @classmethod
    def find(cls, **kwargs):
        """
        get - 
        params: keyword arguments to the model 
        return: Always returned a list
        """
        json_objects = cls().table.search(**kwargs)
        return [cls(o) for o in json_objects]


