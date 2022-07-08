from src.sharedlib.db.APIModel import APIModel


class Character(APIModel):
    API_URL="http://api:8000/character"

    def model_attr(self):
        self.image_url = str
        self.name = str
        self.player_class = str
        self.history = str
        self.hp = int
        self.status = str
        self.inventory = list

    
