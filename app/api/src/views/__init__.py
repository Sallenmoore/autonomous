import random

def package_response(error=None, data=None, count=None):
    return {
        "error":error,
        "results": data,
        "count": count or len(data)
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