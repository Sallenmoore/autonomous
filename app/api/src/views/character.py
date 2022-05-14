# Local Modules
from src.models.campaign.character import Character
from src.views import base_search, package_response

import logging
log = logging.getLogger()

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
    result = base_search(Character)
    return package_response(data=result, count = len(result))

@bp.route('/create', methods=('POST',))
def create():
    """
    _summary_
    """

    new_character = Character(**request.json)
    
    if new_character.save():
        return new_character.serialize()

    character = Character.find(name=request.json.get('pk'))
    return character or {'result':"unknown error"}

@bp.route('/delete', methods=('POST',))
def delete():
    """
    _summary_
    """
    if result := Character.get(**request.json):
        return package_response(data=result.delete(), count = 1)
    return package_response(error="not deleted", count = 0)
    

@bp.route('/<pk>/<character>', methods=('GET',))
def search(pk, character):
    """
    _summary_
    """
    return Character.get(**request.json)
        
