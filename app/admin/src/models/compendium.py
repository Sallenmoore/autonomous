from src.sharedlib.db.APIModel import APIModel

import requests

class Compendium(APIModel):
    AVAILABLE_CLASSES = requests.get(f"http://api:8000/compendium/classes_list").json().get('results')
    


    