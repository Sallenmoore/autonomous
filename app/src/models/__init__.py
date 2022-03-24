from flask import jsonify

class Model:
    API_URL="http://api:8000/"
    
    def serialize(self):
        return jsonify(vars(self))

    def deserialize(self, attrs=None, **data):
        for key in data:
            if not attrs or key in attrs:
                setattr(self, key, data[key])
