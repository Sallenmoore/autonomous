from src.sharedlib.db.APIModel import APIModel
from src.models.action import Action

import requests
from flask import current_app 

class Item(APIModel):
    API_URL="http://api:8000/item"
    def model_attr(self):
        return {
            'name':str,
            'category': str,
            'rarity':str,
            'cost': int,
            "damage_dice": str,
            "damage_type": str,
            "weight": "1 lb.",
            "properties": str,
            'type':str, 
            'img_main':str,
        }
