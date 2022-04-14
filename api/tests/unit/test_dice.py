from src.models.dice import Dice

import d20

def test_roll(test_die):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    for die in test_die:
        assert 0 < Dice(die['dice_str']).roll()
    
def test_num(test_die):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    for die in test_die:
        assert die['num_dice'] ==  Dice(die['dice_str']).num()