import requests
import os
import urllib.parse

class DnDBeyondAPI:

    def __init__(self, url = 'https://character-service.dndbeyond.com/character/v5/character'):
        self.api = url

    def make_query(self, query):
        ## get list of associated pages
        headers= {
            "content-type": "application/json",
            "accept": "application/json"
        }
        url = f"{self.api}/{query}"
        r = requests.get(self.api, headers=headers)

        debug_msg = f'''
            status: {r.status_code} 
            raw response: {r.text},
            encoding: {r.encoding},
            headers: {r.headers},
        '''

        r.raise_for_status()
        res = r.json()

        return  res


    def get_character_updates(self, id):
        response = self.make_query(id)
        return response['data']