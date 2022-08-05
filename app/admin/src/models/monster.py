
from src.sharedlib.db.APIModel import APIModel
from src.models.action import Action

import requests
from flask import current_app 

class Monster(APIModel):
    API_URL="http://api:8000/monster"
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

