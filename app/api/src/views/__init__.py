import random

def package_response(error="", data=None, count=0):
    return {
        "error":error,
        "results": data,
        "count": count
    }


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