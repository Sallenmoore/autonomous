# Local Modules
from src.views import package_response

import logging
log = logging.getLogger()

# External Modules
from flask import (
    Blueprint, request
)

bp = Blueprint('template', __name__, url_prefix='/template')


#################### ENDPOINTS ########################
@bp.route('/', methods=('GET', 'POST'))
def view():
    """
    description

    # METHODS
    post

    # REQUIRED REQUEST DATA
    {
        key:<<str>> (optional)
        key2:<<int>> (optional)
    }

    # RETURN
        Success:
        Error: 
    """

    return package_response(data={})


