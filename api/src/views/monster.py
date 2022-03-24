# Local Modules
from src.models.compendium.monster import Monster

# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

#CONSTANTS
NUM_MONSTERS=1096

bp = Blueprint('monster', __name__, url_prefix='/monster')

@bp.route('/random', methods=('GET',))
def random_monster():
    """
    _summary_
    """
    # returns a Response Object
    results = Monster.search(limit=1, page=random.randrange(1, NUM_MONSTERS+1))
    #current_app.logger.info(f"[{__file__}] results: {results}")
    try:
        return results['results'].pop()
    except KeyError as e:
        return {'error':repr(e)}
        

@bp.route('/search', methods=('GET',))
def search_monsters():
    """
    _summary_
    """
    return (
        Monster.search(**request.args)
        if request.args
        else Monster.search(**request.args)
    )


