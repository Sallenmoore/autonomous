import random

def base_random(model):
    """
    _summary_
    """
    num_results = model.count() + 1
    return model.search(limit=1, page=random.randrange(num_results)+1)
        

def base_search(model, **kwargs):
    """
    _summary_
    """
    return model.search(**kwargs)