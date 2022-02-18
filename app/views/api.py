from models import Player
from flask import (
    Blueprint, current_app, request
)

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.route('/', methods=('GET', 'POST'))
def index():
    return {'calls-available': {'task': ['create', 'get', 'update', 'delete']}}

#################### create methods ###################

