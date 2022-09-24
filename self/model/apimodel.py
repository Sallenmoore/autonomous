from urllib.parse import urlencode, quote
from self.db.basemodel import BaseModel
from self.logger import log
import requests
import pprint
import json
from pydoc import locate


class APIModel(BaseModel):
    """
    _summary_

    _extended_summary_

    Args:
        BaseModel (_type_): _description_

    Raises:
        Exception: _description_
        Exception: _description_

    Returns:
        _type_: _description_
    """
    # TODO: This should be set programmatically
    API_URL="#"

    def __init__(self, **kwargs):
        """
        _summary_

        _extended_summary_

        Raises:
            Exception: _description_
        """
        #log(f"{kwargs.get('pk')}")
        #if the kwargs have a pk, that means this should be an existing record
        if kwargs.get('pk'):
            #set the endpoint to the pk
            #get the current data values
            result = self._get(kwargs['pk'])
            #if there is an error, print it out and throw an exception
            #log(result)
            if result.get("error"):
                raise Exception(response['error'])
            #otherwise, update the object with the current data
            else:
                #update existing attribute dict, then update object
                result['results'].update(kwargs)
                #log(result)
                kwargs = result['results']
                
        super().__init__(**kwargs)


    def delete(self, api_path="delete"):
        """
        _summary_

        _extended_summary_

        Args:
            api_path (str, optional): _description_. Defaults to "delete".

        Returns:
            _type_: _description_
        """
        #log(f"{self.name}:{self.pk}")
        return self._post(api_path, self.serialize())

    def save(self, api_path="create"):
        """
        If the record has a pk, then switches to update. Otherwise,
        creates a new record and sets the pk.

        Args:
            api_path (str, optional): the endpoint save path if not 'create'. Defaults to "create".
        """

        # checks attributes for type
        for k,v in self.attributes.items():
            if hasattr(self, k) and not self.validate(k,getattr(self, k)):
                raise Exception(f"Invalid {self.__class__.__name__} attribute type {k}: {type(v)}")
        
        if hasattr(self, 'pk'):
            api_path = "update"

        result = self._post(api_path, self.serialize())
        if not result.get("error"):
            self.pk = result['results']['pk']
        else:
            raise Exception(result['error'])
        return self.pk

    def model_attr(self, **kwargs):
        attrs = {}
        response = self._get(f"attributes")
        for k,v in response['results'].items():
            attrs[k] = locate(v)
        return attrs

###########################################################################################
##                                     CLASS METHODS                                     ##
###########################################################################################
    
    @classmethod
    def _post(cls, endpoint, data):
        """
        _summary_

        Args:
            endpoint (_type_): _description_
            data (_type_): _description_
            redirect_path (str, optional): _description_. Defaults to "index".

        Returns:
            _type_: _description_
        """
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        #log(data)
        response = requests.post(f"{cls.API_URL}/{endpoint}", json=data, headers=headers)

        return response.json()


    @classmethod
    def _get(cls, endpoint):
        """
        returns the raw json response from a class API endpoint

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        
        response = requests.get(f"{cls.API_URL}/{endpoint}")

        return response.json()

    @classmethod
    def get(cls, pk):
        """
        get a single record from the api based on the pk

        Args:
            pk (int): primary key of the requested record

        Returns:
            dict: a dictionary of the requested record
        """
        
        results =  cls._get(pk)['results']
        obj = cls(**results)
        return obj

    @classmethod
    def search(cls, **kwargs):
        """
        returns objects filtered by search terms
        Args:
            text (_type_, optional): _description_. Defaults to None.
        Returns:
            _type_: _description_
        """
        import urllib.parse

        if kwargs:
            endpoint = f"search?{urllib.parse.urlencode(kwargs)}"
        else:
            endpoint = "all"
        #log(endpoint)
        result = cls._get(endpoint)

        if result.get("error"):
            #log(response['error'])
            raise Exception(response['error'])
        else:
             result = result.get("results")
        return cls.deserialize(result)

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        return cls.search()

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
