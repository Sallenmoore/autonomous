from src.lib import Model
from src.lib import debug_print

from flask import (
    current_app, abort
)

from urllib.parse import urlencode
import requests

class Compendium(Model):
    """
    You can search by property within a specific resource or make a general search
    search options include:
        - search=<term>
        - limit=<num>
    
    (Compendium): A Virtual Proxy class for the open5e api
    """

    resource = ["text"]
    
    API_URL="https://api.open5e.com"

    @classmethod
    def __request(cls, **search_terms):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        search_results = {}
        for r in cls.resource:
            url = cls.__build_url(r, **search_terms)
            #debug_print(url=url)
            search_results[r] = requests.get(url).json()
        #debug_print(search_results=search_results)
        return search_results

    @classmethod
    def __build_url(cls, resource, **search_terms):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """
        url = f"{Compendium.API_URL}/"
        if resource != Compendium.resource[0]:
            url += f"{resource}/?{urlencode(search_terms)}"
        else:
            url += f"search/?{resource}={urlencode(search_terms)}"
        return url
    
    @classmethod
    def search(cls, **search_terms):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        search_results = {'results':[]}
        for v in cls.__request(**search_terms).values():
            search_results['results'] += v.get('results', [])
        return search_results
    
    @classmethod
    def count(cls):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        return sum(v.get('count', 0) for v in cls.__request(limit=1).values())
