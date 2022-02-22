from flask import (
    Blueprint, current_app, request
)

api = Blueprint('api', __name__, url_prefix='/api')

@api.route('/', methods=('GET', 'POST'))
def index():
    return {'calls-available': {'task': ['create', 'get', 'update', 'delete']}}

#################### create methods ###################

