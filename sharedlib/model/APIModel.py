from urllib.parse import urlencode, quote
from flask import redirect, url_for
from .basemodel import BaseModel
import requests
import logging
import pprint
import json
log = logging.getLogger()

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
        log.debug(f"pk: {kwargs.get('pk')}")
        log.debug(f"kwargs: {kwargs}")

        #if the kwargs have a pk, that means this should be an existing record
        if kwargs.get('pk'):
            #set the endpoint to the pk
            #get the current data values
            result = self._get(kwargs['pk'])
            #if there is an error, print it out and throw an exception
            if result.get("error"):
                raise Exception(response['error'])
            #otherwise, update the object with the current data
            else:
                #update existing attribute dict, then update object
                log.debug(f"kwargs: {result['results']}")
                result['results'].update(kwargs)
                log.debug(f"kwargs: {result['results']}")
                super().__init__(**result['results'])
                log.info("===============   PK  =================")
                log.info(self)
        else:
            #create a new object
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
        return self._post(api_path, self.serialize())

    def save(self, api_path="create"):
        """
        If the record has a pk, then switches to update. Otherwise,
        creates a new record and sets the pk.

        Args:
            api_path (str, optional): the endpoint save path if not 'create'. Defaults to "create".
        """
        log.debug("================================")
        log.debug(self)

        for k,v in self.serialize().items():
            if not k.startswith('_') and not self.validate(k,v):
                raise Exception(f"Invalid {self.__class__.__name__} Attribute {k}: {v}")
        
        if hasattr(self, 'pk'):
            log.debug(f"update object: {self.pk}")
            api_path = "update"

        result = self._post(api_path, self.serialize())
        if not result.get("error"):
            self.pk = result['results']['pk']
        else:
            raise Exception(result['error'])
        return self.pk

    ######## Class Methods #########
    
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
        
        log.debug(f"sending data: {data} to: {cls.API_URL}/{endpoint}")
        
        response = requests.post(f"{cls.API_URL}/{endpoint}", json=data, headers=headers)

        log.debug(f"received response: {response.text}")

        return response.json()


    @classmethod
    def _get(cls, endpoint):
        """
        _summary_

        Args:
            endpoint (str): the additional endpoint to append to the API_URL

        Returns:
            dict: the json response from the API converted to a dictionary
        """
        log.debug(f"{cls.API_URL}/{endpoint}")
        response = requests.get(f"{cls.API_URL}/{endpoint}")
        
        log.debug(f"recieved response: {response}")

        return response.json()

    @classmethod
    def get(cls, endpoint):
        """
        get a single record from the api endpoint based on the pk

        Args:
            pk (int): primary key of the requested record

        Returns:
            dict: a dictionary of the requested record
        """
        # NOTE: this is the public method so I can add 
        # transformations later if needed
        
        results =  cls._get(endpoint)
        log.info(results)
        obj = cls(**results)
        log.info(obj)
        return obj

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
        result = cls._get(endpoint)

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
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
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