from sharedlib.model.APIModel import APIModel

from flask import current_app 

class Action(APIModel):
    API_URL="http://api:8000/character"
    def __init__(self, name=None, desc=None, attack=None, dice=None, damage_bonus=None, **kwargs):
        self.name=name
        self.description=desc
        self.attack_bonus=attack
        self.damage_dice=dice
        self.damage_bonus=damage_bonus