# Local Modules
from src.models.compendium.spell import Spell
from src.views import package_response
# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random


bp = Blueprint('spell', __name__, url_prefix='/spell')


@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return packaged_response()