from urllib.parse import urlencode, quote
from flask import redirect, url_for
from .basemodel import BaseModel
from selflib.logger import log
import requests
import pprint
import json
import jsonpickle
from pydoc import locate


class ProxyModel(BaseModel):


    def __init__(self, **kwargs):
        """
        _summary_

        _extended_summary_

        Raises:
            Exception: _description_
        """
        #log(f"kwargs: {kwargs}")
        self.__dict__.update(kwargs)
        


    def delete(self, api_path="delete"):
        """
        _summary_

        _extended_summary_

        Args:
            api_path (str, optional): _description_. Defaults to "delete".

        Returns:
            _type_: _description_
        """
        #log(f"pk: {self.pk}:{type(self.pk)}")
        return self._post(api_path, self.pk) if hasattr(self, "pk") else None

    def save(self, api_path="create"):
        """
        If the record has a pk, then switches to update. Otherwise,
        creates a new record and sets the pk.

        Args:
            api_path (str, optional): the endpoint save path if not 'create'. Defaults to "create".
        """

        if hasattr(self, 'pk'):
            api_path = "update"

        result = self._post(api_path, self)
        if  result.get("error"):
                raise Exception(f"Error sending data: {result['error']}")
        #log(f"result: {result['results']}")
            
        self.pk = result['results'][0].pk
        
        return self.pk

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
        #log(f"endpoint: {endpoint} \ndata:{data.__dict__}")
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        try:
            payload = {'data':jsonpickle.encode(data.__dict__)}
        except AttributeError:
            # log("dictless")
            payload = {'data':jsonpickle.encode(data)}
        #log(f"endpoint: {endpoint}, playload: {payload}")
        response = requests.post(f"{cls.API_URL}/{endpoint}", json=payload, headers=headers)
        response = response.json()
        #log(f"endpoint: {endpoint}, response: {response}")
        response['results'] = cls.deserialize_list(response['results'])
        #log(f"endpoint: {endpoint}, response: {response}")
        return response


    @classmethod
    def _get(cls, endpoint):
        """
        returns the raw json response from a class API endpoint

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        response = requests.get(f"{cls.API_URL}/{endpoint}").json()
        #log(f"endpoint: {endpoint}, response: {response}")
        try:
            response['results'] = cls.deserialize_list(response['results'])
        except Exception as e:
            log(f"Error deserializing results: {e} \n results: {response['results']}")
            raise
        return response

    @classmethod
    def get(cls, pk):
        """
        get a single record from the api based on the pk

        Args:
            pk (int): primary key of the requested record

        Returns:
            dict: a dictionary of the requested record
        """
        
        obj =  cls._get(pk)['results']
        log(f"obj: {obj}")
        return obj[0] if obj else None

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
        #log(result)
        if result.get("error"):
            #log(response['error'])
            raise Exception(response['error'])
        else:
             result = result.get("results")
        #log(result)
        return result

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        return cls.search()
