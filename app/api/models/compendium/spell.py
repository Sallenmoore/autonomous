from sharedlib.model.model import Model


class Spell(Model):
    resource = ["spells", "magicitems"]

    def model_attr(self):
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
