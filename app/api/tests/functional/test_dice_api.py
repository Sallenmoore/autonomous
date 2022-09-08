import urllib
import json
import pytest
from app.app import create_app

@pytest.fixture
def test_client():
    app = create_app()
    # Create a test client using the Flask application configured for testing
    with app.test_client() as testing_client:
        # Establish an application context
        with app.app_context():
            yield testing_client  # this is where the testing happens!
            
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
    
def test_roll(test_client, test_die):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    urls= [ ]
    for ds in test_die:
        url = f'/dice/roll/{urllib.parse.quote(ds["dice_str"])}'
        response = test_client.get(url)
        data = response.data.decode('utf-8')
        results = json.loads(data)
        assert response.status_code == 200
        assert results['number'] == ds['num_dice']
        assert results['result']