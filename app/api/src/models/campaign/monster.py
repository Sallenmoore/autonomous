from src.models import Compendium
from src.sharedlib.db import Model

class Monster(Model, Compendium):
    resource = ["monsters"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            'name':str,  
            'size':str,  
            'type':str,  
            'armor_class':str,  
            'armor_desc':int,  
            'hit_points':int,  
            'hit_dice':str,  
            'challenge_rating':str,  
            'img_main':str,
        }
