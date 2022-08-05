from src.sharedlib.db.APIModel import APIModel


class Template(APIModel):
    API_URL="http://api:8000/template"

    def model_attr(self):
        return {
            "name":str,
        }



    
