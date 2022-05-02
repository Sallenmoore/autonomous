# Local Modules
from src.lib.utilities import debug_print
from src.models.campaign.character import Character
from src.views import base_search, base_random

# External Modules
from flask import (
    Blueprint, request
)

bp = Blueprint('character', __name__, url_prefix='/character')

@bp.route('/all', methods=('GET',))
def all():
    """
    _summary_
    """
    return base_search(Character)

@bp.route('/create', methods=('POST',))
def create():
    """
    _summary_
    """
    debug_print("create api")
    new_character = Character(**request.json)
    
    debug_print(**vars(new_character))
    if new_character.save():
        return new_character.serialize()

    character = Character.find(name=request.json.get('name'))
    return character or {'result':"unknown error"}

@bp.route('/<character>', methods=('GET',))
def search():
    """
    _summary_
    """
    return base_search(Character, **request.args)
        
