from urllib.parse import urlencode
from .basemodel import BaseModel
from autonomous import log
from autonomous.handler import NetworkHandler

import requests
import json
import inspect
import pkgutil
import urllib.parse
    
class ProxyModel(BaseModel):

###########################################################################################
##                                    DUNDER METHODS                                     ##
###########################################################################################

    def __init__(self, **kwargs):
        """
        _summary_

        args:
            - attributes: a dict of attributes and their types

        Raises:
            Exception: _description_
        """
        if kwargs.get('attributes'):
          attributes = kwargs.get('attributes')
        else:
          attributes = NetworkHandler.get(f"{self.API_URL}/attributes",)[0]
        [setattr(self, k, None) for k in attributes]
            
        #log(f"updated values:{kwargs}")
        self._auto_pk = kwargs.pop("_auto_pk", None)
        self.__dict__.update(kwargs)
        if hasattr(self.__class__,"API_MODEL"):
            self._auto_model = self.__class__.API_MODEL
        else:
            self._auto_model = self.__class__.__name__


###########################################################################################
##                                     CLASS METHODS                                     ##
###########################################################################################

    @classmethod
    def get(cls, pk):
        """
        get a single record from the api based on the pk

        Args:
            pk (int): primary key of the requested record

        Returns:
            dict: a dictionary of the requested record
        """
        
        obj =  NetworkHandler.get(f"{cls.API_URL}/{pk}",)
        #log(f"obj: {obj}")
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
        
        if not kwargs: return None
        
        api_path = f"search?{urllib.parse.urlencode(kwargs)}"

        #log(endpoint)
        return NetworkHandler.get(f"{cls.API_URL}/{api_path}")

    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        #log(endpoint)
        return NetworkHandler.get(f"{cls.API_URL}/all")
    
    def save(self, api_path=""):
        """
        If the record has a pk, then switches to update. Otherwise,
        creates a new record and sets the pk.

        Args:
            api_path (str, optional): the endpoint save path if not 'create'. Defaults to "create".
        """
        #log(self)
        self.proxy_auto_models()
        
        result = NetworkHandler.post(f"{self.API_URL}/update", self)
        self._auto_pk = result[0]._auto_pk
        return self._auto_pk

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
        return NetworkHandler.post(f"{self.API_URL}/{api_path}", self.pk)[0] if self.pk else None

    @classmethod
    def delete_all(cls, api_path="deleteall"):
        """
        _summary_

        _extended_summary_

        Args:
            api_path (str, optional): _description_. Defaults to "delete".

        Returns:
            _type_: _description_
        """
        res = NetworkHandler.post(f"{cls.API_URL}/{api_path}", None)
        return res
    
