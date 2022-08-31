# Local Modules
from src.models.dice import Dice

# External Modules
from flask import (
    Blueprint, request, current_app
)


bp = Blueprint('dice', __name__, url_prefix='/dice')

@bp.route('/roll/<string:dice_str>', methods=('GET',))
def roll(dice_str):
    """
    _summary_
    """
    dice = Dice(dice_str, advantage=int(request.args.get("advantage", 0)))
    return {'result':dice.roll(), 'number':dice.num()}


