

from urllib.parse import urlencode, quote
from flask import redirect, url_for
from .model import BaseModel
import requests
import logging
import json
log = logging.getLogger()

class APIModel(BaseModel):
    # TODO: This should be set programmatically
    API_URL="#"

    def __init__(self, pk=None, **kwargs):
        if pk:
            endpoint = f"{pk}"
            result = self.__get(endpoint)
            super().__init__(**result)
        else:
            super().__init__(**kwargs)

    def delete(self, api_path="delete"):
        return self.__post(api_path, self.serialize())

    def save(self, api_path="create"):
        if self.pk is not int:
            api_path = "update"
        return self.__post(api_path, self.serialize())

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
        log.info(f"sending data: {data}")
        response = requests.post(f"{cls.API_URL}/{endpoint}", data=data, headers=headers)
        log.info(f"received response: {response}")
        return response.json

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
        log.info(f"recieved response: {response}")
        return response.json()

    @classmethod
    def search(cls, search_term=None, **kwargs):
        """
        returns objects filtered by search terms
        Args:
            text (_type_, optional): _description_. Defaults to None.
        Returns:
            _type_: _description_
        """
        endpoint = "all"
        if search_term:
            endpoint = f"search?search_term={quote(search_term)}"
        elif kwargs:
            endpoint = f"search?{urlencode(kwargs)}"

        log.debug(endpoint)
        result = cls.__get(endpoint)
        log.debug(result)
        return [cls().update(r) for r in result['results']] if result['results'] else []

    @classmethod
    def all(cls):
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