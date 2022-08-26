

from src.models.compendium.api import API
import requests
from urllib.parse import urlencode
import logging
log = logging.getLogger()

class DnDAPI:
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
        response =  API.all(cls.API_URL, resource)
        return cls._unpack(response)


    @classmethod
    def search(cls, resource, search_term):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        response =  API.search(cls.API_URL, resource, search_term)
        return cls._unpack(response)
        