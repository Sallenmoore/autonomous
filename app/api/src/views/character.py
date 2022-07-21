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

@bp.route('/create', methods=('POST',))
def create():
    """
    _summary_
    """
    log.info(f"request data: {request.json}")
    
    if request.json.get('pk'):
        return package_response(error=="use the /update api for existing characters", count = 0, api_path="/character/update")
    else:
        new_character = Character(**request.json)
    
    if not new_character.save():
        return package_response(data=new_character.serialize(), error="unknown error", count = 1, api_path="/character/create")
    return package_response(data=new_character.serialize(), count = 1, api_path="/character/create")

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
    return package_response(data=results, count = len(results), api_path="/character/all")

@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    log.debug(f"request {vars(request.args)}")
    if not request.args:
        return all()
    results = Character.search(**request.args)
    return package_response(data=results, count = len(results), api_path="/character/search")

@bp.route('/update', methods=('POST',))
def update():
    """
    _summary_
    """
    #log.info(f"request data: {request.json}")
    
    character = Character.get(request.json.get('pk'))

    #log.debug(f"character: {character}")
    
    if not character:
        return package_response(data={'result':"unknown character"}, count = 0)
    
    character.update(**request.json)
    log.debug(f"character: {character}")
    character.save()
    return package_response(data=character.serialize(), count = 1)
    

@bp.route('/delete', methods=('POST',))
def delete():
    """
    _summary_
    """
    pk = request.json.get('pk')
    if result := Character.get(pk):
        log.debug(result)
        return package_response(data=result.delete(), count = 1)
    return package_response(error="not deleted", count = 0)
    

@bp.route('/<pk>', methods=('GET',))
def get(pk):
    """
    _summary_
    """
    result = Character.get(pk)
    return package_response(data=result.serialize() if result else None, count = 1)

