import random
import logging
log = logging.getLogger()

def package_response(error="", data=None, count=0, api_path="/"):
    
    results = {
        "api": api_path,
        "error":error,
        "results": data,
        "count": count
    }
    #log.debug(f"results data: {results}")
    return results


def base_random(model):
    """
    _summary_
    """
    return model.random()

def base_search(model, **kwargs):
    """
    _summary_
    """
    return model.search(**kwargs)