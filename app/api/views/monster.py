# Local Modules
from src.models.campaign.monster import Monster
from src.views import package_response

# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

bp = Blueprint('monster', __name__, url_prefix='/monster')


@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return packaged_response()
