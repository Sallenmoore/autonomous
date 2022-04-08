from flask import jsonify
from src.utilities import DEBUG_PRINT
class Model:
    API_URL="http://api:8000/"
    
    def serialize(self):
        return jsonify(vars(self))

    def deserialize(self, attrs=None, **data):
        DEBUG_PRINT(data)
        for key in data:
            #DEBUG_PRINT(key=key, value=data[key])
            if not self.attrs or key in self.attrs:
                setattr(self, key, data[key])
