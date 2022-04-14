# Local Modules
from src.models.compendium.item import Item
from src.views import base_search, base_random
# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

#CONSTANTS
NUM_ITEMS=1096

bp = Blueprint('items', __name__, url_prefix='/item')

@bp.route('/random', methods=('GET',))
def random_item():
    """
    _summary_
    """
    return base_random(Item)
        

@bp.route('/search', methods=('GET',))
def search_items():
    """
    _summary_
    """
    return base_search(Item, **request.args)

@bp.route('/all', methods=('GET',))
def all_items():
    """
    _summary_
    """
    request.args.clear()
    return search_items()
