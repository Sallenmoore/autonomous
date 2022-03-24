# Local Modules
from src.models.compendium import Compendium

from flask import (
    Blueprint, request, current_app
)

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

@bp.route('/search/', methods=('GET',))
def search(term=""):
    """
    _summary_
    """
    return Compendium.search(**request.args)