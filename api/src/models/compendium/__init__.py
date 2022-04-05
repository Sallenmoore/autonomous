from src.db.model import Model

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
    def search(cls, **search_terms):
        """
        _summary_
        """
        search_results = {}
        for r in cls.resource:
            url = f"{Compendium.API_URL}/"
            if r != Compendium.resource[0]:
                url += f"{r}/?{urlencode(search_terms)}"
            else:
                url += f"search/?{r}={urlencode(search_terms)}"
            print(f"\t**DEBUG**: url={url}")
            try:
                search_results[r] = { **search_results, **requests.get(url).json()}
            except requests.JSONDecodeError as e:
                search_results[r] = {'error!':str(e)}
        print(f"\t**DEBUG**: cls.search_results={search_results}")
        return search_results

    @classmethod
    def count(cls):
        return sum(r.get('count', 0) for r in cls.search().values())
