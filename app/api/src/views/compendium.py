# Local Modules
from src.models.compendium import Compendium
from src.models.compendium.charclass import CharClass
from src.views import package_response
from flask import (
    Blueprint, request, current_app
)

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

@bp.route('/random', methods=('GET',))
def random():
    """
    _summary_
    """
    return Compendium.random()
        

@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return Compendium.search(**request.args)

@bp.route('/all', methods=('GET',))
def all():
    """
    _summary_
    """
    results = Compendium.search()
    return package_response(data=results, count = len(results), api_path="/compendium/all")

@bp.route('/classes_list', methods=('GET',))
def classes_list():
    """
    _summary_
    """
    results = CharClass.all()
    return package_response(data=results, count = len(results), api_path="/compendium/all")


    