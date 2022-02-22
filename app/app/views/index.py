from flask import (
    Blueprint, current_app, request
)

index_bp = Blueprint('index', __name__, url_prefix='/')

@index_bp.route('/', methods=('GET', 'POST'))
def index():
    return {'calls-available': {'task': ['create', 'get', 'update', 'delete']}}

#################### create methods ###################

