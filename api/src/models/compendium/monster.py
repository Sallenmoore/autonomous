from src.models import Compendium

from flask import (
    current_app
)
import requests

class Monster(Compendium):

    @classmethod
    def search(cls, **search_terms):
        """
        _summary_
        """
        # current_app.logger.debug(f"\n\n==========DEBUG\n\n{monster}")
        # if not monster.get('img_main'):
        #     #res = requests.get(f"???").json()
        #     monster['img_main'] = res['thumbnail']
        return Compendium.search(resource="monsters", **search_terms)