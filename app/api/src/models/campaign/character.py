from src.sharedlib.db import Model
from src.models.wikiAPI import WikiAPI
import requests
import os

import logging
log = logging.getLogger()

class Character(Model):
    """
    _summary_

    _extended_summary_

    Args:
        Model (_type_): _description_

    """
        

    def model_attr(self):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
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

    def wiki_pull(self):
        wk = WikiAPI()
        res = wk.wikipull(title=self.name, assets_path=['assets', 'dnd'])
        if res:
            self.image_url = res.get('asset_url', '')
            content = res.get('content')
            if content:
                start = content.find("## Character History") + len("## Character History")
                end = content.find("---", start)
                if not start != -1:
                    end = len(content)-1 if end == -1 else end
                    self.history = content[start:end]
            self.save()
   
    @classmethod
    def search(cls, **kwargs):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        objs = cls.find(**kwargs) if kwargs else cls.all()
        o_list = []
        for o in objs:
            o.wiki_pull()
            o_list.append(o.serialize())
        return o_list

## TODO - additional attributes
# {
# "status": "success",
# "data": {
#     "id": "",
#     "name": "",
#     "description": "",
#     "url": "",
#     "image": "",
#     "type": "",
#     "subtype": "",
#     "source": "",
#     "page": "",
#     "cost": "",
#     "weight": "",
#     "special": "",
#     "ability": "",
#     "armor": "",
#     "hp": "",
#     "ac": "",
#     "str": "",
#     "dex": "",
#     "con": "",
#     "int": "",
#     "wis": "",
#     "cha": "",
#     "speed": "",
#     "str_save": "",
#     "dex_save": "",
#     "con_save": "",
#     "int_save": "",
#     "wis_save": "",
#     "cha_save": "",
#     "skills": [
#         {
#             "name": "",
#             "ability": "",
#             "modifier": "",
#             "proficient": ""
#         }
#     ],
#     "senses": "",
#     "passive_perception": "",
#     "languages": "",
#     "challenge_rating": "",
#     "traits": [
#         {
#             "name": "",
#             "description": ""
#         }
#     ],
#     "actions": [
#         {
#             "name": "",
#             "description": ""
#         }
#     ],
#     "reactions": []
# }