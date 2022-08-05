# Local Modules
from src.models.compendium.item import Item
from src.views import package_response
# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

#CONSTANTS
NUM_ITEMS=1096

bp = Blueprint('items', __name__, url_prefix='/item')


@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return packaged_response()

