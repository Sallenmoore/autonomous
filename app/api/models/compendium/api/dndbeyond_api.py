import requests
import os
import urllib.parse

from sharedlib.logger import log

class DnDBeyondAPI:

    def __init__(self, url = 'https://character-service.dndbeyond.com/character/v5/character'):
        self.api = url

    def make_query(self, query):
        ## get list of associated pages
        url = f"{self.api}/{query}"
        r = requests.get(url)

        debug_msg = f'''
            status: {r.status_code},
            text: {r.text},
            headers: {r.headers},
        '''
        #log(f"url: {url} r:{debug_msg}")
        
        r.raise_for_status()
        res = r.json()

        return  res


    def get_character_updates(self, id):
        response = self.make_query(id)
        return response['data']