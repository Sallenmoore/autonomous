# Local Modules
from src.models.spell import Spell
from src.views import base_search, base_random
# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random


bp = Blueprint('spell', __name__, url_prefix='/spell')


@bp.route('/random', methods=('GET',))
def random_spell():
    """
    _summary_
    """
    return base_random(Spell)
    
        

@bp.route('/search', methods=('GET',))
def search_spells():
    """
    _summary_
    """
    return base_search(Spell, **request.args)


@bp.route('/all', methods=('GET',))
def all_spells():
    """
    _summary_
    """
    return base_search(Spell)