from src.lib import debug_print
from src.models.compendium.api import DnDAPI

from flask import (
    current_app, abort
)

from urllib.parse import urlencode
import requests

import random

class Compendium:
    """
    You can search by property within a specific resource or make a general search
    search options include:
        - search=<term>
        - limit=<num>
    
    (Compendium): A Virtual Proxy class for the open5e api
    """

    resource = ["search"]
    
    @classmethod
    def search(cls, search_term=None, **search_terms):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        #get each resource results
        search_terms['search'] = search_term
        #debug_print(search_results=len(search_results['results']))
        return DnDAPI.api_request(cls.resource, **search_terms)
    
    @classmethod
    def count(cls, **search_terms):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        return DnDAPI.api_request(cls.resource, **search_terms).get('count', 0)

    @classmethod
    def random(cls):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        random_resource = random.choice(cls.resource)
        num_pages = DnDAPI.api_request([random_resource], limit=1).get('count', 0)
        #debug_print(random_resource=random_resource, num_pages=num_pages)
        result = DnDAPI.api_request([random_resource], limit=1, page=random.randrange(num_pages)+1)
        result['count'] = 1
        result['next'] = ""
        return result
        
        
