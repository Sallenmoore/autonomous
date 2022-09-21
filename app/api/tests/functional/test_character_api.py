import urllib
import json
import pytest
from app.app import create_app
from models.campaign.character import Character

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
    yield {
            "name": "Test Character", 
            "image_url": "test.png", 
            "player_class": "Test", 
            "history": "Test", 
            "hp": 100, 
            "status": "None", 
            "inventory": ["Test Item #1", "Test Item #2"],
            "active": True,
        }

#################### Convenience Functions ####################

def after_test_cleanup():
    chars = Character.find(player_class="Test")
    if chars:
        for char in chars:
            char.delete()

def temp_character_object(test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    ch = Character(**test_char)
    ch.save()
    return ch

def verify_results(r):
    """
    _summary_

    Args:
        results (_type_): _description_

    Returns:
        _type_: _description_
    """
    return all([r.get('image_url') == "test.png",
            r.get('player_class') == "Test",
            r.get('history') == "Test", 
            r['name']
        ])

def filtered_results(results):
    return [r for r in results if verify_results(r)]

#################### TESTING ####################

def test_all(test_client, test_char):
    """
    _summary_

    Returns:
        _type_: _description_
    """

    temp_character_object(test_char)
    response = test_client.get('/character/all')
    assert response.status_code == 200
    results = response.json
    assert not results['error']
    assert results['count'] > 0
    for r in results['results']:
        assert r['name']
    after_test_cleanup()


def test_character_create(test_client, test_char):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    response = test_client.post('/character/create', json=test_char)
    assert response.status_code == 200
    response = test_client.get('/character/all')
    results = response.json
    assert not results['error']
    assert results['count'] > 0
    for r in results['results']:
        assert r['name']
    after_test_cleanup()

def test_update(test_client, test_char):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    temp_character_object(test_char)
    response = test_client.get('/character/all').json
    for c in filtered_results(response['results']):
        c['hp'] = 50
        c['inventory'].append("Test Item #3")

        response = test_client.post('/character/update', json=c).json

        
    response = test_client.get('/character/all').json
    for c in filtered_results(response['results']):
        assert c['hp'] == 50
        assert "Test Item #3" in c['inventory']
    after_test_cleanup()

def test_get(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    temp_character_object(test_char)
    response = test_client.get('/character/all').json
    for c in filtered_results(response['results']):
        response = test_client.get(f'/character/{c["pk"]}').json
        assert response['results']['pk'] == c['pk']
    after_test_cleanup()

def test_character_get_attributes(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    response = test_client.get('/character/attributes').json
    assert "name" in response['results']

def test_search(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    temp_character_object(test_char)
    response = test_client.get('/character/all').json
    for c in filtered_results(response['results']):
        url = f'/character/search?{urllib.parse.urlencode({"name":c["name"]})}'
        result = test_client.get(url).json
        assert filtered_results(result['results'])
        
        url = f'/character/search?{urllib.parse.urlencode({"player_class":c["player_class"]})}'
        result = test_client.get(url).json
        assert filtered_results(result['results'])
    after_test_cleanup()
        
def test_delete(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    temp_character_object(test_char)
    response = test_client.get('/character/all').json
    for c in filtered_results(response['results']):
            test_client.post('/character/delete', json={"pk":c["pk"]}).json
            
    response = test_client.get('/character/all').json
    data =  filtered_results(response['results'])
    assert len(data) == 0