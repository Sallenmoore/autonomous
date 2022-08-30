
from src.models.compendium.dndapi import DnDAPI
from src.models.compendium.spell import Spell
from src.models.compendium.monster import Monster
from src.models.compendium.item import Item

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
    You can search by keyword within a specific resource or make a general search
    search options include:
        - search_term=<term>
    
    (Compendium): A Virtual Proxy class for the general open5e api
    """

    resource = ["search"]
    
    @classmethod
    def search(cls, search_term, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        result = DnDAPI.search(cls.resource, search_term)
        results = []
        log.debug(result)
        for r in result:
            routes = {
                    'spells/': Spell, 
                    'monsters/': Monster, 
                    'magicitems/': Item, 
                    'weapons/':Item, 
                    'armor/':Item, 
            }
            if r.get('route') in routes:
                route_cls = routes[r['route']]
                m = route_cls.find(name=r['name'])
                log.debug(f"find: {m}")
                if m:
                    m = m.pop()
                    m.update(**r)
                else: 
                    m = route_cls(**r)
                log.debug(f"m: {m}")
                m.save()
            else:
                m = r
            results.append(m)
        return results
