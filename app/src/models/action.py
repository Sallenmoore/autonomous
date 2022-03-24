from src.models import Model

from flask import current_app 

class Action(Model):
    def __init__(self, name=None, desc=None, attack=None, dice=None, damage_bonus=None, **kwargs):
        self.name=name
        self.description=desc
        self.attack_bonus=attack
        self.damage_dice=dice
        self.damage_bonus=damage_bonus