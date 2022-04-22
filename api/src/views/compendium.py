# Local Modules
from src.models.compendium import Compendium
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