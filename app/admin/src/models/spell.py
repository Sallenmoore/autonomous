from src.sharedlib.db.APIModel import APIModel
from src.models.action import Action

import requests
from flask import current_app 

class Spell(APIModel):
    API_URL="http://api:8000/spell"
    
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

