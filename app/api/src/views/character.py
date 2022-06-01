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
    return all Character models as dict:
    {
        error:<str>
        results:<obj> or None
        count: <int> , length of <obj>
    }
    """
    results = Character.search()
    return package_response(data=results, count = len(results))

@bp.route('/create', methods=('POST',))
def create():
    """
    _summary_
    """

    new_character = Character(**request.json)
    log.debug(f"request data: {request.json}")
    if new_character.save():
        return package_response(data=new_character.serialize(), count = 1)

    character = Character.get(name=request.json.get('pk'))
    return package_response(data=character or {'result':"unknown error"}, count = 1)

@bp.route('/update', methods=('POST',))
def update():
    """
    _summary_
    """
    log.info(f"request data: {request.json}")
    character = Character.get(request.json.get('pk', request.json.get('doc_id', None)))
    #log.info(f"character:{vars(character)}")
    if character.update(**request.json):
        character.save()
        return package_response(data=character.serialize(), count = 1)
    return package_response(data={'result':"unknown character"}, count = 0)

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
        
