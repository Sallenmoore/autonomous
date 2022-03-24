from src.models.dice import Dice

import d20

def test_roll(die_str):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    assert 0 < Dice(die_str[0]).roll()
    
def test_num(die_str):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    assert Dice(die_str[0]).num() == die_str[1]