
from api.db.model import Model

from flask import app, abort, jsonify

from urllib.parse import urlencode
import requests
import logging

log = logging.getLogger('app.compendium')

API_URL="https://api.open5e.com"
class Compendium(Model):
    """
    You can search by property within a specific resource or make a general search
    search options include:
        - search=<term>
        - limit=<num>
        -  
    
    (Compendium): A Virtual Proxy class for the open5e api
    """
    
    @classmethod
    def __search(cls, **search_terms):
        """
        _summary_
        """
        url = f"{API_URL}/{search_terms.pop('resource')}/?{urlencode(search_terms)}"
        results = requests.get(url).json()
        return jsonify(results) if results else abort(404, description="no results")
    
    @classmethod
    def search_monsters(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="monsters", **search_terms)
    
    @classmethod
    def search_spells(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="spells", **search_terms)
    
    @classmethod
    def search_documents(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="documents", **search_terms)
    
    @classmethod
    def search_backgrounds(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="backgrounds", **search_terms)
    
    @classmethod
    def search_planes(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="planes", **search_terms)
    
    @classmethod
    def search_sections(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="sections", **search_terms)
    
    @classmethod
    def search_feats(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="feats", **search_terms)
    
    @classmethod
    def search_conditions(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="conditions", **search_terms)
    
    @classmethod
    def search_races(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="races", **search_terms)
    
    @classmethod
    def search_classes(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="classes", **search_terms)
    
    @classmethod
    def search_magicitems(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="magicitems", **search_terms)
    
    @classmethod
    def search_weapons(cls, **search_terms):
        """
        _summary_
        """
        return cls.__search(resource="weapons", **search_terms)
    
    @classmethod
    def search(cls, search_term=""):
        """
        _summary_
        """
        return cls.__search(resource="search", text=search_term)
