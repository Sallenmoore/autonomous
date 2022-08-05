from src.models import Compendium
from src.sharedlib.db import Model

class Item(Model, Compendium):
    resource = ["magicitems", "weapons"]

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
            'quantity':int,
        }