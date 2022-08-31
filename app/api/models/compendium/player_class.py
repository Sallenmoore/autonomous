from sharedlib.model.model import Model

import logging
log = logging.getLogger()

class PlayerClass(Model):
    resource = ["classes"]

    def model_attr(self):
        #current_app.logger.info(kwargs)
        return {
            "name": str,
            "slug": str,
            "desc": str,
            "hit_dice": str,
            "hp_at_1st_level": str,
            "hp_at_higher_levels": str,
            "prof_armor": str,
            "prof_weapons": str,
            "prof_tools": str,
            "prof_saving_throws": str,
            "prof_skills": str,
            "equipment": str,
            "table": str,
            "spellcasting_ability": str
        }

    @classmethod
    def list(cls, refresh=False):
        from models.compendium.compendium import Compendium
        class_list = Compendium.class_list(refresh=refresh)
        log.info(class_list)
        return [cl.name for cl in class_list]
        
