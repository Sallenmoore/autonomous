# Local Modules
from sharedlib.logger import log
from views import package_response

# External Modules
from flask import (
    Blueprint, request
)

bp = Blueprint('template', __name__, url_prefix='/template')


#################### CREATE ENDPOINTS ########################
@bp.route('/create', methods=('POST',))
def create():
    """
    create model

    Returns:
        {
            error:<str>,  
            results:<obj> or None, 
            count: <int> , 
            api_path:<str>
        }
    """
    log(f"request data: {request}")
    return package_response(data="")

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
    return package_response(data="")

@bp.route('/<pk>', methods=('GET',))
def get(pk):
    """
    _summary_
    """
    return package_response(data="")

@bp.route('/search', methods=('GET',))
def search():
    """
    search for a character using the given key/value pairs
    in the request data.

    Returns:
        list: a list of matching character models in serialized form
    """
    log(f"{request}")
    return package_response(data=results)

@bp.route('/attributes', methods=('GET',))
def attributes():
    """
    _summary_
    """
    log(f"{request}")
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
    log(f"{request}")
    return package_response(data=results)

#################### DELETE ENDPOINTS ########################

@bp.route('/delete', methods=('POST',))
def delete():
    """
    _summary_
    """
    log(f"{request}")
    return package_response(data=results)

