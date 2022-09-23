from sharedlib.model.APIModel import APIModel
from .monster import Monster
from .spell import Spell
from .item import Item
from .character import Character
from .player_class import PlayerClass

from sharedlib.logger import log
import requests
from config import Config
from urllib.parse import quote

class Compendium(APIModel):
    """

    _extended_summary_

    Args:
        APIModel (_type_): _description_

    Returns:
        _type_: _description_
    """
    
    API_URL=f"http://api:{Config.API_PORT}/compendium"

    @classmethod
    def deserialize(cls, result):
        objects = []
        for r in result:
            
            if "Spell" in r.get('model_class'):
                o = Spell(**r)
            elif "Item" in r.get('model_class'):
                o = Item(**r)
            elif "Monster" in r.get('model_class'):
                o = Monster(**r)
            elif "Character" in r.get('model_class'):
                o = Character(**r)
            elif "PlayerClass" in r.get('model_class'):
                o = PlayerClass(**r)
            #log(o)

            objects.append(o)
        return objects

    