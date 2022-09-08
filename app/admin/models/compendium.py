from sharedlib.model.APIModel import APIModel
import logging
import requests

log = logging.getLogger()

class Compendium(APIModel):
    """

    _extended_summary_

    Args:
        APIModel (_type_): _description_

    Returns:
        _type_: _description_
    """
    
    API_URL="http://api:44666/compendium"
    

    @classmethod
    def search(cls, search=None, endpoint="search"):
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        data = {
            'search_term':search
        }
        url = f"{cls.API_URL}/{endpoint}"
        log.debug(url )
        response = requests.post(url, json=data, headers=headers)
        results = response.json()
        log.debug(results['results'])
        return results
    


    