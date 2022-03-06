from flask import (
    Blueprint, request, url_for
)

from api.models import Compendium

bp = Blueprint('compendium', __name__, url_prefix='/compendium')

@bp.route('/search_monsters', methods=('GET',))
def search_monsters():
    """
    _summary_
    """
    return Compendium.search_monsters(**request.args)

@bp.route('/search_spells', methods=('GET',))
def search_spells():
    """
    _summary_
    """
    return Compendium.search_spells(**request.args)

@bp.route('/search_documents', methods=('GET',))
def search_documents():
    """
    _summary_
    """
    return Compendium.search_documents(**request.args)

@bp.route('/search_backgrounds', methods=('GET',))
def search_backgrounds():
    """
    _summary_
    """
    return Compendium.search_backgrounds(**request.args)

@bp.route('/search_planes', methods=('GET',))
def search_planes():
    """
    _summary_
    """
    return Compendium.search_planes(**request.args)

@bp.route('/search_sections', methods=('GET',))
def search_sections():
    """
    _summary_
    """
    return Compendium.search_sections(**request.args)

@bp.route('/search_feats', methods=('GET',))
def search_feats():
    """
    _summary_
    """
    return Compendium.search_feats(**request.args)

@bp.route('/search_conditions', methods=('GET',))
def search_conditions():
    """
    _summary_
    """
    return Compendium.search_conditions(**request.args)

@bp.route('/search_races', methods=('GET',))
def search_races():
    """
    _summary_
    """
    return Compendium.search_races(**request.args)

@bp.route('/search_classes', methods=('GET',))
def search_classes():
    """
    _summary_
    """
    return Compendium.search_classes(**request.args)

@bp.route('/search_magicitems', methods=('GET',))
def search_magicitems():
    """
    _summary_
    """
    return Compendium.search_magicitems(**request.args)

@bp.route('/search_weapons', methods=('GET',))
def search_weapons():
    """
    _summary_
    """
    return Compendium.search_weapons(**request.args)

@bp.route('/search', methods=('GET',))
def search():
    """
    _summary_
    """
    return Compendium.search(**request.args)