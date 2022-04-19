from src.models import Model
from src.models.action import Action

import requests
from flask import current_app 

class Spell(Model):
    API_URL = f"{Model.API_URL}spell"
    
    def __init__(self, **kwargs):
        #current_app.logger.info(kwargs)
        self.attrs = {
            'name':None, 
            'range':None, 
            'duration':None, 
            'casting_time':None, 
            'school':None, 
            'rarity':None, 
            'type':'spell', 
            'img_main':None,
        }

        self.deserialize(**kwargs)

