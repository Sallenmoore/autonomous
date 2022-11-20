from autonomous.model.model import Model
from models.submodeltest import SubModelTest

class ModelTest(Model): 
    attributes = {
        "name":str, 
        "sub":SubModelTest, 
        "collection":list, 
        "value":int,
        "nothing":int, 
        "keystore":dict
        }