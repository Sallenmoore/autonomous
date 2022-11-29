from autonomous.model.model import Model
from models.submodeltest import SubModelTest
from datetime import datetime

class ModelTest(Model): 
    attributes = {
        "name":str, 
        "sub":SubModelTest, 
        "collection":list, 
        "value":int,
        "nothing":int, 
        "keystore":dict,
        "timestamp":datetime
        }