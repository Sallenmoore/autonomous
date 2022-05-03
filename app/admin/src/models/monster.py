
from src.models import Model
from src.models.action import Action

import requests
from flask import current_app 

class Monster(Model):
    API_URL = f"{Model.API_URL}monster"
    def __init__(self,  **kwargs):
        #current_app.logger.info(kwargs)
        self.attrs = {
            'name':None,  
            'size':None,  
            'type':None,  
            'armor_class':None,  
            'armor_desc':None,  
            'hit_points':None,  
            'hit_dice':None,  
            'challenge_rating':None,  
            'img_main':None,
        }
        self.deserialize(**kwargs)
        self.actions = [Action(**action) for action in kwargs.get('actions')] if kwargs.get('actions') else []

