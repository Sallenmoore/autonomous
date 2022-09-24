from self.db.APIModel import APIModel
import os

class Template(APIModel):
    API_URL=f"http://api:{os.envvars('API_PORT')}/template"

    def model_attr(self):
        return {
            "name":str,
        }



    
