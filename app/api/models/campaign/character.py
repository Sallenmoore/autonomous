from sharedlib.model.model import Model
import requests
import os

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
   
    @classmethod
    def search(cls, **kwargs):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        
        objs = cls.find(**kwargs) if kwargs else cls.all()
        return objs
    