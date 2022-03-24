
from src.db.model import Model

from flask import (
    current_app, abort
)

from urllib.parse import urlencode
import requests
import logging

log = logging.getLogger('app.compendium')

class Compendium(Model):
    """
    You can search by property within a specific resource or make a general search
    search options include:
        - search=<term>
        - limit=<num>
    
    (Compendium): A Virtual Proxy class for the open5e api
    """

    API_URL="https://api.open5e.com"
    
    @classmethod
    def search(cls, resource=None, **search_terms):
        """
        _summary_
        """
        url = f"{Compendium.API_URL}/"
        if not resource:
            url += f"search/?text={search_terms.get('text')}"
        else:
            url += f"{resource}/?{urlencode(search_terms)}"
        results = requests.get(url).json()
        #current_app.logger.info(f"results: {results}")
        return results or abort(404, description="no results")
