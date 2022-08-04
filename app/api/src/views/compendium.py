# Local Modules
from src.models.compendium import Compendium
from src.views import package_response
from flask import (
    Blueprint, request, current_app
)
import logging
log = logging.getLogger()

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

@bp.route('/random', methods=('GET',))
def random():
    """
    returns a random item, monster, or spell 
    TODO: add filters to results for item generation
    
    Returns:
        dict: {
                error:<str>, 
                results:random item, 
                count: 1 , 
                api_path:/compendium/random
            }
    """
    results = Compendium.random()
    return package_response(data=results)
        

@bp.route('/classes_list', methods=('GET',))
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
    results = Compendium.classes_list()
    return package_response(data=results)

@bp.route('/search', methods=('GET',))
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
    results = Compendium.search(**request.json)
    return package_response(data=results)

@bp.route('/all', methods=('GET',))
def all():
    """
    returns all content in the compendium (WARNING: this is a large list)

    Returns:
        dict: {
                error:<str>, 
                results: list of all content, 
                count: <int>, 
                api_path:/compendium/all
            }
    """
    results = Compendium.search()
    return package_response(data=results)
