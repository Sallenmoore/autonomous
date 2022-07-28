from src.models import Compendium
from src.sharedlib.db import Model

class Spell(Model, Compendium):
    resource = ["spells", "magicitems"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            'name':str, 
            'range':int, 
            'duration':str, 
            'casting_time':str, 
            'school':str, 
            'rarity':str, 
            'type':str, 
            'img_main':str,
        }

