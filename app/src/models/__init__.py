from src.lib import debug_print

from urllib.parse import urlencode, quote

from flask import current_app, jsonify
import requests

class Model:
    API_URL="http://api:8000/"
    
    def serialize(self):
        return jsonify(vars(self))

    def deserialize(self, attrs=None, **data):
        #debug_print(data)
        for key in data:
            #debug_print(key=key, value=data[key])
            if key in self.attrs:
                setattr(self, key, data[key] or self.attrs[key])

    ######## CLass Methods #########

    @classmethod
    def search(cls, search_term=None, **kwargs):
        """
        returns objects filtered by search terms

        Args:
            text (_type_, optional): _description_. Defaults to None.

        Returns:
            _type_: _description_
        """
        if search_term:
            url = f"{cls.API_URL}/search?search_term={quote(search_term)}"
        else:
            url = f"{cls.API_URL}/search?{urlencode(kwargs)}"
        result = requests.get(url).json()
        #debug_print(url=url, result=result['results'])
        return [cls(**r) for r in result['results']]

    @classmethod
    def random(cls):
        """
        returns a random object

        Returns:
            _type_: _description_
        """
        url = f"{cls.API_URL}/random"
        #debug_print(url=url)
        result = requests.get(url)
        #debug_print(result=result)
        result = result.json()
        debug_print(result=result)
        return cls(**result['results'])