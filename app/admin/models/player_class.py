from sharedlib.model.APIModel import APIModel
from config import Config

class PlayerClass(APIModel):
    API_URL=f"http://api:{Config.API_PORT}/compendium/player_class"
