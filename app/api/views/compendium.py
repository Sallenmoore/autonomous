# Local Modules
from models.compendium import Compendium
from views import package_response
from sharedlib.logger import log

# external modules
from flask import (
    Blueprint, request, current_app
)
bp = Blueprint('compendium', __name__, url_prefix='/compendium')


####################################################################
##                    Update DB Data                              ##
####################################################################

@bp.route('/update_compendium', methods=('GET',))
def dbupdate():
    response = Compendium.update_compendium()
    return package_response(data=response)

####################################################################
##                    general   search                            ##
####################################################################
@bp.route('/all', methods=('GET',))
@bp.route('/search', methods=('GET',))
def search():
    """
    keyword search to search the compendium
    
    accepts url paramter: `<key>`:`<value>`

    Returns:
        dict: {
                error:<str>, 
                results: list of matches, 
                count: <int>, 
                api_path:/compendium/search
            }
    """
    #log(request.args)
    response = Compendium.search(**request.args)
    #.FIXME Ensure unique values - probably a better way
    names = []
    to_remove = []
    i = 0
    while i < len(response):
        if response[i].name not in names:
            names.append(response[i].name)
            i+=1
        else:
            del response[i]
    results = [o.serialize() for o in response]
    return package_response(data=results)

####################################################################
##                    item      search                            ##
####################################################################
@bp.route('/item/all', methods=('GET',))
@bp.route('/item/search', methods=('GET',))
def item():
    """
    keyword search to search the compendium based on key/value pairs

    Returns:
        dict: {
                error:<str>, 
                results: list of matches, 
                count: <int>, 
                api_path:/compendium/search
            }
    """
    results = Compendium.item_search(**request.args)
    results = [r.serialize() for r in results]
    return package_response(data=results)

@bp.route('/item/attributes', methods=('GET',))
def item_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    results = Compendium.item_attrs()
    results = {k:v.__name__ for k,v in results.items()}
    return package_response(data=results)

@bp.route('/item/<pk>', methods=('GET',))
def get_item(pk):
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = Compendium.get_item(pk).serialize()
    return package_response(data=results)

####################################################################
##                    monster   search                            ##
####################################################################
@bp.route('/monster/all', methods=('GET',))
@bp.route('/monster/search', methods=('GET',))
def monster():
    """
    keyword search to search the compendium based on key/value pairs

    Returns:
        dict: {
                error:<str>, 
                results: list of matches, 
                count: <int>, 
                api_path:/compendium/search
            }
    """
    results = Compendium.monster_search(**request.args)
    results = [r.serialize() for r in results]
    return package_response(data=results)

@bp.route('/monster/attributes', methods=('GET',))
def monster_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    results = Compendium.monster_attrs()
    results = {k:v.__name__ for k,v in results.items()}
    return package_response(data=results)

@bp.route('/monster/<pk>', methods=('GET',))
def get_monster(pk):
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = Compendium.get_monster(pk).serialize()
    return package_response(data=results)

####################################################################
##                    spell     search                            ##
####################################################################
@bp.route('/spell/all', methods=('GET',))
@bp.route('/spell/search', methods=('GET',))
def spell():
    """
    keyword search to search the compendium based on key/value pairs

    Returns:
        dict: {
                error:<str>, 
                results: list of matches, 
                count: <int>, 
                api_path:/compendium/search
            }
    """
    results = Compendium.spell_search(**request.args)
    results = [r.serialize() for r in results]
    return package_response(data=results)

@bp.route('/spell/attributes', methods=('GET',))
def spell_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    results = Compendium.spell_attrs()
    results = {k:v.__name__ for k,v in results.items()}
    return package_response(data=results)

@bp.route('/spell/<pk>', methods=('GET',))
def get_spell(pk):
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = Compendium.get_spell(pk).serialize()
    return package_response(data=results)

####################################################################
##                    player class search                         ##
####################################################################
@bp.route('/player_class/all', methods=('GET',))
def classes_list():
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = [cl.serialize() for cl in Compendium.class_list()]
    return package_response(data=results)

@bp.route('/player_class/attributes', methods=('GET',))
def player_class_attributes():
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = Compendium.player_class_attrs()
    results = {k:v.__name__ for k,v in results.items()}
    return package_response(data=results)

@bp.route('/player_class/<pk>', methods=('GET',))
def get_player_class(pk):
    """
    returns a list of available character classes

    Returns:
        dict: {
                error:<str>, 
                results:<list> or None, 
                count: <int> , 
                api_path:/combendium/classes_list
            }
    """
    results = Compendium.get_class(pk).serialize()
    return package_response(data=results)