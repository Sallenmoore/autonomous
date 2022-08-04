
from src.models.compendium.api import DnDAPI

from flask import (
    current_app, abort
)
import random
import requests
from urllib.parse import urlencode

import logging
log = logging.getLogger()



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
        log.debug(search_terms)
        if search_term:
            search_terms['search'] = search_term
        
        response = DnDAPI.api_request(cls.resource, **search_terms, full_api_results=True).get('results')
        log.debug(response)
        return response
    
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
        
        result = DnDAPI.api_request([random_resource], limit=1, page=random.randrange(num_pages)+1)
        return result['results']

    @classmethod
    def classes_list(cls):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result = DnDAPI.api_request(['classes'], full_api_results=True)
        classes = []
        for r in result['results']:
            classes.append(r['name'])
            log.debug(f"{r['name']}") 

        log.debug(classes)
        
        return classes
        
