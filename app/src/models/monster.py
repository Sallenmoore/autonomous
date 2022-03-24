from src.models import Model
from src.models.action import Action

import requests
from flask import current_app 

class Monster(Model):
    API_URL=f"{Model.API_URL}monster"

    def __init__(self, **kwargs):
        self.API_URL += "monster"
        #current_app.logger.info(kwargs)
        attrs = [
            'name', 
            'size', 
            'type', 
            'armor_class', 
            'armor_desc', 
            'hit_points', 
            'hit_dice', 
            'challenge_rating', 
            'img_main'
        ]
        self.deserialize(attrs=attrs, **kwargs)
        #current_app.logger.info(json_data.get('actions'))
        self.actions = [Action(**action) for action in kwargs.get('actions')]
        #current_app.logger.info(self.actions)
    ######## CLass Methods #########

    @classmethod
    def random(cls):
        """
        returns a random monster object pulled from the API

        Returns:
            _type_: _description_
        """
        url = f"{cls.API_URL}/random"
        result = requests.get(url).json()
        return cls(**result)
