# Local Modules
from src.models.campaign.monster import Monster
from src.views import base_search, base_random

# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

bp = Blueprint('monster', __name__, url_prefix='/monster')


@bp.route('/random', methods=('GET',))
def random_monster():
    """
    _summary_
    """
    return base_random(Monster)
        

@bp.route('/search', methods=('GET',))
def search_monsters():
    """
    _summary_
    """
    return base_search(Monster, **request.args)

@bp.route('/all', methods=('GET',))
def all_monsters():
    """
    _summary_
    """
    return base_search(Monster)
