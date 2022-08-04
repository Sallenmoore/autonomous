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
    Create a new character based on request data with a primary key

    # METHOD
    post

    # REQUIRED REQUEST DATA
    {
        image_url:<str> (optional)
        self.name:<str> (required)
        self.player_class:<str> (required)
        self.history:<str> (optional)
        self.hp:<int> (optional)
        self.status:<str> (optional)
        self.inventory:<list> (optional)
    }

    # RETURN
        Success: {
                    error:"unknown character",  
                    results: character attributes in serialized form, 
                    count: 1, 
                    api_path:/character/create
               }
               
        Error: {
                    error:"use the /update api for existing characters"|| "Character could not be saved. Unknown error.",  
                    results:None, 
                    count: 0, 
                    api_path:/character/activate
               }
    """
    log.debug(f"request data: {request.json}")
    
    if request.json.get('pk'):
        return package_response(error="use the /update api for existing characters", api_path="/character/update")
    else:
        new_character = Character(**request.json)
    
    if not new_character.save():
        return package_response(error="Character could not be saved. Unknown error.")
    return package_response(data=new_character.serialize())

#################### READ ENDPOINTS ########################
@bp.route('/all', methods=('GET',))
def all():
    """
     All character models in serialized form

    Returns:
        {
            error:<str>,  
            results:<obj> or None, 
            count: <int> , 
            api_path:<str>
        }
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
    Update one or more attributes for the character with the given primary key
    * METHOD: post
    * REQUIRED REQUEST DATA: 
        {
            pk:<int>,
            <...additonal attributes>: <updated value>
        }

    Returns:
        updated character attributes in serialized form
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

@bp.route('/activate', methods=('POST',))
def activate():
    """
    Activate the character with the given primary key

    # METHOD
    post

    # REQUIRED REQUEST DATA
    Format: json
    {
        pk: int 
    }

    # Return
        Success: {
                    error:"unknown character",  
                    results: updated character attributes in serialized form, 
                    count: 1, 
                    api_path:/character/activate
               }
               
        Error: {
                    error:"unknown character",  
                    results:None, 
                    count: 0, 
                    api_path:/character/activate
               }
    """
    #log.info(f"request data: {request.json}")
    
    character = Character.get(request.json.get('pk'))

    #log.debug(f"character: {character}")
    
    if not character:
        return package_response(error="unknown character")
    
    character.active=True
    log.debug(f"character: {character}")
    character.save()
    return package_response(data=character.serialize())

@bp.route('/deactivate', methods=('POST',))
def deactivate():
    """
    Deactivate the character with the given primary key
    * METHOD: post
    * REQUIRED REQUEST DATA: {pk:<int>}
    """
    #log.info(f"request data: {request.json}")
    
    character = Character.get(request.json.get('pk'))

    #log.debug(f"character: {character}")
    
    if not character:
        return package_response(error="unknown character")
    
    character.active=False
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

