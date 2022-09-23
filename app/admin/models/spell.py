from sharedlib.model.APIModel import APIModel
from config import Config

class Spell(APIModel):
    API_URL=f"http://api:{Config.API_PORT}/compendium/spell"

