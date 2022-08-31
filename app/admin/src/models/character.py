from src.sharedlib.db.APIModel import APIModel


class Character(APIModel):
    API_URL="http://api:44666/character"

    def model_attr(self):
        return {
            "image_url":str,
            "name":str,
            "player_class":str,
            "history":str,
            "hp":int,
            "status":str,
            "inventory":list,
            "active":bool,
        }



    
