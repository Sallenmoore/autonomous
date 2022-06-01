

from urllib.parse import urlencode, quote

from .model import BaseModel
import requests
import logging
log = logging.getLogger()

class APIModel(BaseModel):
    API_URL="http://api:8000/"
    
    def serialize(self):
        return vars(self)

    def deserialize(self, attrs=None, **data):
        #(data)
        for key in data:
            #(key=key, value=data[key])
            if key in self.attrs:
                setattr(self, key, data[key] or self.attrs[key])

    ######## Class Methods #########

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
        
        return [cls(**r) for r in result['results']]

    @classmethod
    def random(cls):
        """
        returns a random object

        Returns:
            _type_: _description_
        """
        url = f"{cls.API_URL}/random"
        result = requests.get(url)
        result = result.json()
        try:
            return cls(**result['results'].pop())
        except Exception as e:
            return None