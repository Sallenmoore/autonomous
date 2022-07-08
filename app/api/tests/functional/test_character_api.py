import urllib
import json
import pytest
from src import create_app
import logging
log = logging.getLogger()

@pytest.fixture
def test_client():
    app = create_app()
    # Create a test client using the Flask application configured for testing
    with app.test_client() as testing_client:
        # Establish an application context
        with app.app_context():
            yield testing_client  # this is where the testing happens!
            
@pytest.fixture
def test_char():
    record = {
        "name":"Test Character", 
        "image_url":"test.png",
        "player_class":"Test",
        "history":"Test",
        "hp":100,
        "status":"None",
        "inventory":["Test Item #1", "Test Item #2"]
    }
    yield record

def test_create(test_client, test_char):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    #log.debug(f'test_char: {test_char}')
    response = test_client.post('/character/create', json=test_char)
    #log.debug(f'response: {response}')
    assert response.status_code == 200
    data = response.json
    assert not data['error']
    assert data['count'] == 1
    assert data['results']['name'] == test_char['name']



def test_search(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """

    response = test_client.get('/character/search')
    assert response.status_code == 200
    data = response.json
    #TODO: test the data

    url = f'/character/search?{urllib.parse.urlencode({"name":test_char["name"]})}'
    response = test_client.get(url)
    assert response.status_code == 200
    data = response.json
    #TODO: test the data

def test_delete(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    test_client.post('/character/create', json=test_char)
    response = test_client.get('/character/all').json
    for c in response['results']:
        if c['name'] == test_char['name']:
            response = test_client.post(f'/character/delete', json={"pk":c["pk"]})
            assert response.status_code == 200
    response = test_client.get('/character/all')
    data = response.json
    assert data['count'] == 0
