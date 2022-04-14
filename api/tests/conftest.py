from src import create_app
import pytest

@pytest.fixture(scope='module')
def test_client():
    app = create_app()
    # Create a test client using the Flask application configured for testing
    with app.test_client() as testing_client:
        # Establish an application context
        with app.app_context():
            yield testing_client  # this is where the testing happens!

@pytest.fixture(scope='module')
def test_search_endpoints():

    return {
        'monster':{}, 
        'spell':{},
        'item':{},
        'compendium':{},
        }

@pytest.fixture(scope='module')
def test_random_endpoints():
    return ['monster', 'spell','item','compendium']

@pytest.fixture(scope='module')
def test_die():

    return [
        {"dice_str": "3d10+4", "num_dice":3}, 
        {"dice_str": "1d20+5", "num_dice":1}, 
        {"dice_str": "4d6kh3", "num_dice":3},
        {"dice_str": "3d10+4", "num_dice":3, "advantage":1}, 
        {"dice_str": "1d20+5", "num_dice":1, "advantage":-1}, 
        {"dice_str": "4d6kh3", "num_dice":3, "advantage":0},
        ]
