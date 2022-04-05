# Local Modules
from src.models.campaign.character import Character

# External Modules
from flask import (
    Blueprint, request, current_app
)

# Python Modules
import random

#CONSTANTS
NUM_MONSTERS=1096

bp = Blueprint('character', __name__, url_prefix='/character')

@bp.route('/random', methods=('GET',))
def random_character():
    """
    _summary_
    """
    return {"result":"success"}
        

@bp.route('/search', methods=('GET',))
def search_characters():
    """
    _summary_
    """
    return {"result":"success"}


