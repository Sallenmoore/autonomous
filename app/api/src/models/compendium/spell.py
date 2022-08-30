from src.sharedlib.db import Model
from src.models.compendium.dndapi import DnDAPI

import logging
log = logging.getLogger()

class Spell(Model):
    resource = ["spells", "magicitems"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            'name':str, 
            'range':int,
            "desc": str,
            "higher_level": str,
            "range": str,
            "ritual": str,
            "duration": str,
            "concentration": str, 
            'casting_time':str, 
            'school':str, 
            'type':str, 
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
        spells = []
        log.debug(result)
        for r in result:
            m = cls.find(name=r['name'])
            log.debug(f"find: {m}")
            if m:
                m = m.pop()
                m.update(**r)
            else: 
                m = Spell(**r)
            log.debug(f"m: {m}")
            m.save()
            spells.append(m)
        return spells