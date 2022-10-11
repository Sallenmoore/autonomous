from selflib.model.model import Model

class ModelTest(Model): 
    attributes = {
        "name":str, 
        "status":str, 
        "collection":list, 
        "value":int,
        "nothing":int, 
        "keystore":dict
        }