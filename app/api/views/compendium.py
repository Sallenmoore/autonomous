# Local Modules
from models.compendium import Compendium
from views import package_response
from flask import (
    Blueprint, request, current_app
)
import logging
log = logging.getLogger()

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

REFRESH=False

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
    results = [cl.serialize() for cl in Compendium.class_list(refresh=REFRESH)]
    return package_response(data=results)

@bp.route('/player_class/attributes', methods=('GET',))
def classes_list_attributes():
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
    results = [cl.serialize() for cl in Compendium.class_list(refresh=REFRESH) if cl.pk == pk]
    return package_response(data=results)
####################################################################
##                              search                            ##
####################################################################
@bp.route('/search', methods=('POST',))
def search():
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
    log.debug(f"{request.json}")
    response = Compendium.search(**request.json)
    results = [o.serialize() for o in response]
    return package_response(data=results)

@bp.route('/item', methods=('POST',))
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
    log.debug(f"{request.json}")
    results = Compendium.item_search(**request.json)
    return package_response(data=results.serialize())

@bp.route('/item/attributes', methods=('GET',))
def item_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    log.debug(f"{request.json}")
    results = Compendium.item_attrs()
    result = {k:str(v) for k,v in result.items()}
    return package_response(data=results)


@bp.route('/monster', methods=('POST',))
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
    log.debug(f"{request.json}")
    results = Compendium.monster_search(**request.json)
    return package_response(data=results.serialize())

@bp.route('/monster/attributes', methods=('GET',))
def monster_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    log.debug(f"{request.json}")
    results = Compendium.monster_attrs()
    results = {k:str(v) for k,v in result.items()}
    return package_response(data=results)

@bp.route('/spell', methods=('POST',))
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
    log.debug(f"{request.json}")
    results = Compendium.spell_search(**request.json)
    return package_response(data=results.serialize())

@bp.route('/spell/attributes', methods=('GET',))
def spell_attributes():
    """
    _summary_

    _extended_summary_

    Returns:
        _type_: _description_
    """
    log.debug(f"{request.json}")
    results = Compendium.spell_attrs()
    results = {k:str(v) for k,v in result.items()}
    return package_response(data=results)

