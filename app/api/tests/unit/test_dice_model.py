from src.models.dice import Dice
import pytest
import d20

@pytest.fixture
def test_die():

    return [
        {"dice_str": "3d10+4", "num_dice":3}, 
        {"dice_str": "1d20+5", "num_dice":1}, 
        {"dice_str": "4d6kh3", "num_dice":3},
        {"dice_str": "3d10+4", "num_dice":3, "advantage":1}, 
        {"dice_str": "1d20+5", "num_dice":1, "advantage":-1}, 
        {"dice_str": "4d6kh3", "num_dice":3, "advantage":0},
        ]

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