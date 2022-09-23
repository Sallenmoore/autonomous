
from sharedlib.model.APIModel import APIModel
from config import Config

class Monster(APIModel):
    API_URL=f"http://api:{Config.API_PORT}/compendium/monster"
