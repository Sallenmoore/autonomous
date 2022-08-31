from sharedlib.model.APIModel import APIModel
from models.action import Action

import requests
from flask import current_app 

class Spell(APIModel):
    API_URL="http://api:44666/compendium/spell"
    
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

