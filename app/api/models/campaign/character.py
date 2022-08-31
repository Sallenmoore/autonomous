from sharedlib.model.model import Model
from models.compendium.api.wiki_api import WikiAPI
from models.compendium.compendium import Compendium
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
            "dndbeyond_id":int,
            "active":bool,
        }

    def api_update(self):
        dndbeyond = Compendium.character_update(self)
        # wk = WikiAPI()
        # res = wk.wikipull(title=self.name, assets_path=['assets', 'dnd'])
        # if res:
        #     self.image_url = res.get('asset_url', '')
        #     content = res.get('content')
        #     if content:
        #         start = content.find("## Character History") + len("## Character History")
        #         end = content.find("---", start)
        #         if not start != -1:
        #             end = len(content)-1 if end == -1 else end
        #             self.history = content[start:end]
        #     self.save()
   
    @classmethod
    def search(cls, **kwargs):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        objs = cls.find(**kwargs) if kwargs else cls.all()
        for o in objs:
            o.api_update()
        return objs
    