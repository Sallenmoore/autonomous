

from urllib.parse import urlencode, quote
from flask import redirect, url_for
from .model import BaseModel
import requests
import logging
import pprint
import json
log = logging.getLogger()

class APIModel(BaseModel):
    # TODO: This should be set programmatically
    API_URL="#"

    def __init__(self, **kwargs):
        log.debug(f"pk: {kwargs.get('pk')}")
        log.debug(f"kwargs: {kwargs}")
        if kwargs.get('pk') and len(kwargs) == 1:
            endpoint = kwargs.get('pk')
            result = self.__get(endpoint)
            if result.get("error"):
                log.error(response['error'])
                raise Exception(response['error'])
            else:
                result = result.get("results")
        else:
            super().__init__(**kwargs)

    def delete(self, api_path="delete"):
        return self.__post(api_path, self.serialize())

    def save(self, api_path="create"):

        log.info(f"pk: {self.pk}")
        
        if type(self.pk) == int:
            
            log.info(f"update pk: {self.pk}")

            api_path = "update"

        result = self.__post(api_path, self.serialize())

        log.debug(result)

        self.pk = result['results'].get('pk')

    def __repr__(self):
        return pprint.pformat(vars(self))

    ######## Class Methods #########
    
    @classmethod
    def __post(cls, endpoint, data, redirect_path="index"):
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
        
        log.debug(f"sending data: {data} to: {cls.API_URL}/{endpoint}")
        
        response = requests.post(f"{cls.API_URL}/{endpoint}", json=data, headers=headers)

        log.debug(f"received response: {response.text}")

        return response.json()


    @classmethod
    def __get(cls, endpoint, redirect_path="index"):
        """
        _summary_

        Args:
            endpoint (_type_): _description_
            redirect_path (str, optional): _description_. Defaults to "index".

        Returns:
            _type_: _description_
        """
        response = requests.get(f"{cls.API_URL}/{endpoint}")
        #log.info(f"recieved response: {response}")
        return response.json()

    @classmethod
    def get(cls, pk):
        return cls.__get(pk)

    @classmethod
    def search(cls, search_term=None, **kwargs):
        """
        returns objects filtered by search terms
        Args:
            text (_type_, optional): _description_. Defaults to None.
        Returns:
            _type_: _description_
        """
        log.debug("searching...")
        endpoint = "all"
        if search_term:
            endpoint = f"search?search_term={quote(search_term)}"
        elif kwargs:
            endpoint = f"search?{urlencode(kwargs)}"
        log.debug(endpoint)
        result = cls.__get(endpoint)

        if result.get("error"):
            log.error(response['error'])
            raise Exception(response['error'])
        else:
            result = result.get("results")
        log.debug(result)
        objects = []
        for r in result:
            log.debug(r)
            o = cls(**r)
            log.debug(o)
            objects.append(o)
        return objects

    @classmethod
    def all(cls):
        log.debug("all...")
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