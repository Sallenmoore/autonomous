# Local Modules
from src.lib.utilities import debug_print
from src.models.compendium import Compendium
from src.models.compendium.charclass import CharClass
from src.views import base_search, base_random
from flask import (
    Blueprint, request, current_app
)

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

@bp.route('/random', methods=('GET',))
def random():
    """
    _summary_
    """
    return base_random(Compendium)
        

@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return base_search(Compendium, **request.args)

@bp.route('/all', methods=('GET',))
def all():
    """
    _summary_
    """
    return base_search(Compendium)

@bp.route('/classes_list', methods=('GET',))
def classes_list():
    """
    _summary_
    """
    results = base_search(CharClass).get('results')
    return {'results': [c.get('name') for c in results]}
    