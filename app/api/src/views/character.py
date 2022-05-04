# Local Modules
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

    new_character = Character(**request.json)
    
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
        
