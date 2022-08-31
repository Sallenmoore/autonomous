
from models.compendium.api.opendnd_api import OpenDnDAPI
from models.compendium.api.dndbeyond_api import DnDBeyondAPI
from models.compendium.api.wiki_api import WikiAPI
from models.compendium.spell import Spell
from models.compendium.monster import Monster
from models.compendium.item import Item
from models.compendium.player_class import PlayerClass

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
    def _find_and_update(cls, model, r):
        m = model.find(name=r['name'])
        log.debug(f"find: {m}")
        if m:
            m = m.pop()
            m.update(**r)
        else: 
            m = model(**r)
        log.debug(f"m: {m}")
        m.save()
        return m

    @classmethod
    def search(cls, search_term=None, model=None, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        if model:
            result = model.all()
            if not refresh and result:
                return result
        else:
            model = Compendium

        result = OpenDnDAPI.search(model.resource, search_term) if search_term else OpenDnDAPI.all(model.resource)

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
                m = cls._find_and_update(routes[r['route']], r)
            elif model != Compendium:
                m = cls._find_and_update(model, r)
            results.append(m)
        return results

    @classmethod
    def item_search(cls, search_term, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        return Compendium.search(search_term=search_term, model=Item, refresh=refresh)


    @classmethod
    def monster_search(cls, search_term, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        return Compendium.search(search_term=search_term, model=Monster, refresh=refresh)

    @classmethod
    def spell_search(cls, search_term, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        return Compendium.search(search_term=search_term, model=Spell, refresh=refresh)

    @classmethod
    def class_list(cls, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        return Compendium.search(model=PlayerClass, refresh=refresh)

    @classmethod
    def character_update(cls, character):
        """
        _summary_

        _extended_summary_

        Args:
            id (_type_): _description_

        Returns:
            _type_: _description_
        """
        if hasattr(character, 'dndbeyond_id'): 
            beyond_api = DnDBeyondAPI()
            result =  beyond_api.get_character_updates(character.dndbeyond_id)
            log.info(result)
            return result
        return None