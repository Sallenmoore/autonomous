from src.sharedlib.db import Model
from src.models.compendium.dndapi import DnDAPI

import logging
log = logging.getLogger()

class Monster(Model):
    resource = ["monsters"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            'name':str,  
            'size':str,  
            'type':str,  
            'armor_class':str,  
            'armor_desc':int,  
            'hit_points':int,  
            'hit_dice':str,  
            'challenge_rating':str,  
            'img_main':str,
        }

    @classmethod
    def search(cls, search_term, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        result = cls.all()
        if not refresh and result:
            return [r.name for r in result]
        
        result = DnDAPI.search(cls.resource, search_term)
        monsters = []
        log.debug(result)
        for r in result:
            m = cls.find(name=r['name'])
            log.debug(f"find: {m}")
            if m:
                m = m.pop()
                m.update(**r)
            else: 
                m = Monster(**r)
            log.debug(f"m: {m}")
            m.save()
            monsters.append(m)
        return monsters