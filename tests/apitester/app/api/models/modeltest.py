from autonomous.model.model import Model
from .submodeltest import SubModelTest
from datetime import datetime

class ModelTest(Model): 
    def autoattributes(self):
        #log(self)
        return {
            "name":str, 
            "sub":SubModelTest, 
            "collection":list, 
            "value":int,
            "nothing":str, 
            "keystore":dict,
            "timestamp":datetime
        }