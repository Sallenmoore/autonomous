from models.compendium.api.base_api import BaseAPI
import requests
from urllib.parse import urlencode

import logging
log = logging.getLogger()

class OpenDnDAPI:
    """
    _summary_

    Returns:
        _type_: _description_
    """
    API_URL = "https://api.open5e.com/"

    @classmethod
    def _unpack(cls, response):
        results = []
        for r in response['results'].values():
            results += r['results']
        return results

    @classmethod
    def all(cls, resource):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        response =  BaseAPI.all(cls.API_URL, resource)
        log.info(f"response: {response}")
        return cls._unpack(response)


    @classmethod
    def search(cls, resource, search_term=None):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        response =  BaseAPI.search(cls.API_URL, resource, search_term) if search_term else BaseAPI.all(cls.API_URL, resource)
        return cls._unpack(response)
        