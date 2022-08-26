from src.sharedlib.db import Model
from src.models.compendium.dndapi import DnDAPI

import logging
log = logging.getLogger()

class Item(Model):
    resource = ["magicitems", "weapons", "armor"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            "name": str,
            "type": str,
            "category": str,
            "cost": str,
            "desc": str,
            "damage_dice": str,
            "damage_type": str,
            "weight": str,
            "ac_string": str,
            "strength_requirement": str,
            "rarity": str,
            "requires_attunement": str,
            "stealth_disadvantage": bool,
            "properties": list,
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
        items = []
        log.debug(result)
        for r in result:
            m = cls.find(name=r['name'])
            log.debug(f"find: {m}")
            if m:
                m = m.pop()
                m.update(**r)
            else: 
                m = Item(**r)
            log.debug(f"m: {m}")
            m.save()
            items.append(m)
        return items