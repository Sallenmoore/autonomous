from src.sharedlib.db.APIModel import APIModel
from src.models.action import Action

import requests
from flask import current_app 

class Item(APIModel):
    API_URL="http://api:8000/item"
    def __init__(self,  **kwargs):
        #current_app.logger.info(kwargs)
        self.attrs = {
            'name':None,
            'category': 'magic',
            'rarity':None,
            'cost': 0,
            "damage_dice": None,
            "damage_type": None,
            "weight": "1 lb.",
            "properties": None,
            'type':'weapon', 
            'img_main':None,
        }
        self.deserialize(**kwargs)
