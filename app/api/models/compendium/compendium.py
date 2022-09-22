
from models.compendium.api.opendnd_api import OpenDnDAPI
from models.compendium.api.dndbeyond_api import DnDBeyondAPI
from models.compendium.api.wiki_api import WikiAPI
from models.compendium.spell import Spell
from models.compendium.monster import Monster
from models.compendium.item import Item
from models.compendium.player_class import PlayerClass
from models.campaign.character import Character

from sharedlib.logger import log

from flask import (
    current_app, abort
)
import random
import requests
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor



class Compendium:
    """
    You can search by keyword within a specific resource or make a general search
    search options include:
        - search_term=<term>
    
    (Compendium): A Virtual Proxy class for the general open5e api
    """

    resource = ["search"]
    apis = [Spell,Monster,Item,PlayerClass]

    ############ Methods for updating the db using various apis ############

    @classmethod
    def update_compendium(cls):
        """
        Update the compendium with the latest data from the apis
        """
        log("Updating Compendium")
        # DOCS https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.ThreadPoolExecutor
        executor = ThreadPoolExecutor(2)
        executor.submit(Compendium.updatedb)
        executor.submit(Compendium.update_characters)
        log("Compendium Updated")
        return "success"

    @classmethod
    def updatedb(cls):
        ### OpenDND API
        opendnd5e = OpenDnDAPI()
        results = []
        for model in cls.apis:
            results = opendnd5e.get(model.resource)
            log(f"updating {model.__name__} with {len(results)} entries...")
            for r in results:
                m = model.find(name=r['name'])
                if m:
                    m = m.pop()
                    m.update(**r)
                else: 
                    m = model(**r)
                m.save()
                log(f"updating: {r['name']}")
            log(f"[{m.model_class}] -- updated")

    @classmethod
    def update_characters(cls, characters=None):
        characters = characters if characters else Character.all()
        for ch in characters:
            cls.update_character(ch)

    @classmethod
    def update_character(cls, ch):
        beyond_api = DnDBeyondAPI()
        if hasattr(ch, 'dndbeyond_id') and ch.dndbeyond_id: 
            result =  beyond_api.get_character_updates(ch.dndbeyond_id)
            
            # log(result['name'])
            # log(result['race']['fullName'])
            # log(result['decorations']['avatarUrl'])
            # log(result['classes'][0]['definition']['name'])
            # log(result["notes"]["backstory"])
            # log(result['baseHitPoints'])
            # log(";".join(f"{result['conditions']}"))
            # log([name['definition']['name'] for name in result['inventory']])
            
            updates = {
                "name":result['name'],
                "race":result['race']['fullName'],
                "image_url":result['decorations']['avatarUrl'],
                "player_class":result['classes'][0]['definition']['name'],
                "history":result["notes"]["backstory"],
                "hp":result['baseHitPoints'],
                "status":";".join(f"{result['conditions']}"),
                "inventory":[name['definition']['name'] for name in result['inventory']],
            }
            #log(updates)
            ch.update(**updates)
            ch.save()
            log(f"{ch.name} -- updated")
            
    @classmethod
    def all(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        return cls.search()

    @classmethod
    def search(cls, model=None, **kwargs):
        results = []
        apis = [model] if model else cls.apis
        if kwargs.get('name'):
            kwargs['name'] = kwargs['name'].split()
        #log(kwargs)
        for model in apis:
            results += model.find(**kwargs) if kwargs else model.all()
        #log(len(results))
        return results

    @classmethod
    def item_all(cls):
        return cls.item_search()

    @classmethod
    def item_search(cls, **kwargs):
        return Compendium.search(model=Item, **kwargs)

    @classmethod
    def get_item(cls, pk):
        return Item.get(pk)


    @classmethod
    def item_attrs(cls):
        return Item().model_attr()

    @classmethod
    def monster_all(cls):
        return cls.monster_search()

    @classmethod
    def monster_search(cls, **kwargs):
        return Compendium.search(**kwargs, model=Monster)

    @classmethod
    def get_monster(cls, pk):
        return Monster.get(pk)

    @classmethod
    def monster_attrs(cls):
        return Monster().model_attr()

    @classmethod
    def spell_all(cls):
        return cls.spell_search()
    
    @classmethod
    def spell_search(cls, **kwargs):
        return Compendium.search(**kwargs, model=Spell)

    @classmethod
    def get_spell(cls, pk):
        return Spell.get(pk)

    @classmethod
    def spell_attrs(cls):
        return Spell().model_attr()

    @classmethod
    def class_list(cls):
        return PlayerClass.all()

    @classmethod
    def get_class(cls, pk):
        return PlayerClass.get(pk)

    @classmethod
    def player_class_attrs(cls):
        return PlayerClass().model_attr()
