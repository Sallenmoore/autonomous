from models.compendium.api.base_api import BaseAPI
from sharedlib.logger import log

import requests
from urllib.parse import urlencode


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
            #log(f"r: {r}")
            results += r['results']
            #log(f"results: {results}")
        return results

    @classmethod
    def get(cls, resource):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        response =  BaseAPI.get(cls.API_URL, resource)
        return cls._unpack(response)
        