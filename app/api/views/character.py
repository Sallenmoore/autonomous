# Local Modules
from models.campaign.character import Character
from models.compendium.compendium import Compendium
from sharedlib.logger import log
from views import package_response

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
                    api_path:/character/create
               }
    """
    
    if request.json.get('pk'):
        return package_response(error="use the /update api for existing characters", api_path="/character/update")
    else:
        new_character = Character(**request.json)
    
    if not new_character.save():
        return package_response(error="Character could not be saved. Unknown error.")
    return package_response(data=new_character.serialize())

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
    
    character = Character.get(request.json.get('pk'))
    
    if not character:
        return package_response(error="unknown character")
    character.update(**request.json)
    character.save()
    return package_response(data=character.serialize())


#################### DELETE ENDPOINTS ########################

@bp.route('/delete', methods=('POST',))
def delete():
    """
    _summary_
    """
    pk = request.json.get('pk')
    #log(pk)
    if result := Character.get(pk):
        #log(result)
        return package_response(data=result.delete())
    return package_response(error="not deleted")

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
    results = Character.all()
    Compendium.update_characters(results)
    results = [c.serialize() for c in results]
    return package_response(data=results)

@bp.route('/attributes', methods=('GET',))
def attributes():
    """
    _summary_
    """
    result = Character().model_attr()
    result = {k:v.__name__ for k,v in result.items()}
    return package_response(data=result)

@bp.route('/search', methods=('GET',))
def search():
    """
    search for a character using the given key/value pairs
    in the request data.

    Returns:
        list: a list of matching character models in serialized form
    """
    log(request.args)
    if not request.args:
        return all()
    response = Character.search(**request.args)
    Compendium.update_characters(response)
    results = [r.serialize() for r in response]
    return package_response(data=results)

@bp.route('/<int:pk>', methods=('GET',))
def get(pk):
    """
    _summary_
    """
    Compendium.update_characters()
    result = Character.get(pk)
    return package_response(data=result.serialize() if result else None)