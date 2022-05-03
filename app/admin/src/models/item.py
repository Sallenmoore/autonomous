from src.models import Model
from src.models.action import Action

import requests
from flask import current_app 

class Item(Model):
    API_URL = f"{Model.API_URL}item"
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
