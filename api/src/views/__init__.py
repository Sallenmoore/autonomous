import random

def base_random(model):
    """
    _summary_
    """
    num_results = model.count() + 1
    results = model.search(limit=1, page=random.randrange(num_results)+1)
    return {"result":results}
        

def base_search(model, **kwargs):
    """
    _summary_
    """
    return model.search(**kwargs)