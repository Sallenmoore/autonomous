# Local Modules
from src.models.campaign.character import Character
from src.views import package_response

import logging
log = logging.getLogger()

# External Modules
from flask import (
    Blueprint, request
)

bp = Blueprint('character', __name__, url_prefix='/character')


#################### CREATE ENDPOINTS ########################
@bp.route('/create', methods=('POST',))
def create():
    """
    Create a new character based on requeast data with a primary key.
    The request data should be a json object with the following keys:
    {
        image_url:<str> (optional)
        self.name:<str> (required)
        self.player_class:<str> (required)
        self.history:<str> (optional)
        self.hp:<int> (optional)
        self.status:<str> (optional)
        self.inventory:<list> (optional)
    }
    Returns:
        dict: new character data with assocu=iated primary key
    """
    log.debug(f"request data: {request.json}")
    
    if request.json.get('pk'):
        return package_response(error="use the /update api for existing characters", api_path="/character/update")
    else:
        new_character = Character(**request.json)
    
    if not new_character.save():
        return package_response(error="Charactetr coulds not be saved. Unknown error.")
    return package_response(data=new_character.serialize())

#################### READ ENDPOINTS ########################
@bp.route('/all', methods=('GET',))
def all():
    """
     All character models in serialized form

    Returns:
        dict:{error:<str>,  results:<obj> or None, count: <int> , api_path:<str>}
    """
    
    results = Character.search()
    return package_response(data=results)

@bp.route('/<pk>', methods=('GET',))
def get(pk):
    """
    _summary_
    """
    result = Character.get(pk)
    return package_response(data=result.serialize() if result else None)

@bp.route('/search', methods=('GET',))
def search():
    """
    search for a character using the given key/value pairs
    in the request data.

    Returns:
        list: a list of matching character models in serialized form
    """
    log.debug(f"request {vars(request.args)}")
    if not request.args:
        return all()
    results = Character.search(**request.args)
    return package_response(data=results)

#################### UPDATE ENDPOINTS ########################

@bp.route('/update', methods=('POST',))
def update():
    """
    _summary_
    """
    #log.info(f"request data: {request.json}")
    
    character = Character.get(request.json.get('pk'))

    #log.debug(f"character: {character}")
    
    if not character:
        return package_response(error="unknown character")
    
    character.update(**request.json)
    log.debug(f"character: {character}")
    character.save()
    return package_response(data=character.serialize())

#################### DELETE ENDPOINTS ########################

@bp.route('/delete', methods=('POST',))
def delete():
    """
    _summary_
    """
    pk = request.json.get('pk')
    if result := Character.get(pk):
        log.debug(result)
        return package_response(data=result.delete())
    return package_response(error="not deleted")

