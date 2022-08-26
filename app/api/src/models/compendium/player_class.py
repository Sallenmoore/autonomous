from src.sharedlib.db import Model
from src.models.compendium.dndapi import DnDAPI

import logging
log = logging.getLogger()

class PlayerClass(Model):
    resource = ["classes"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            'name':str,
            'desc':str  
        }

    @classmethod
    def list(cls, refresh=False):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        classes = []
        result = cls.all()
        
        if not refresh and result:
            return [r.name for r in result]
        
        result = DnDAPI.all('classes')
        classes = []
        log.debug(result)
        for r in result:
            pc = PlayerClass.find(name=r['name'])
            log.debug(f"find: {pc}")
            if pc:
                pc = pc.pop()
                pc.update(**r)
            else: 
                pc = PlayerClass(**r)
            log.debug(f"pc: {pc}")
            pc.save()
            classes.append(pc.name)
        return classes
        
