from src.sharedlib.db.APIModel import APIModel
import logging
import requests

log = logging.getLogger()

class Compendium(APIModel):
    """

    _extended_summary_

    Args:
        APIModel (_type_): _description_

    Returns:
        _type_: _description_
    """
    
    API_URL="http://api:8000/compendium"
    
    @classmethod
    def get_classes(cls):
        """
        _summary_

        _extended_summary_

        Returns:
            _type_: _description_
        """
        results = cls.get(f"classes_list")

        log.debug(f"results: {results}")

        return results['results']
    


    