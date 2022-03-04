import requests


class Monster:
    API_URL="http://api:8000/api"

    def __init__(self, **kwargs):
        print(kwargs)



    ######## CLass Methods #########

    @classmethod
    def get_random_monster(cls):
        """
        returns a random monster object pulled from the API

        Returns:
            _type_: _description_
        """
        result = requests.get(f"{cls.API_URL}/random_monster").json()
        return cls(result)
