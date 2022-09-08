import urllib
import json
import pytest
from app.app import create_app
from models.campaign.character import Character
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
            r.get('name') == "Test Character",
            r.get('player_class') == "Test",
            r.get('history') == "Test",
        ])

def filtered_results(results):
    return [r for r in results if verify_results(r)]

#################### TESTING ####################

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
    assert data['count'] > 0
    assert verify_results(data['results'])

def test_all(test_client, test_char):
    """
    _summary_

    Returns:
        _type_: _description_
    """

    temp_character_object(test_char)
    #log.debug(f'test_char: {test_char}')
    response = test_client.get('/character/all')
    #log.debug(f'response: {response}')
    assert response.status_code == 200
    data = response.json
    assert not data['error']
    assert data['count'] > 0
    assert len(filtered_results(data['results'])) > 0
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

        log.info(f'response: {response}')
        
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
        log.info(response)
        assert response['results']['pk'] == c['pk']
    after_test_cleanup()

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

def test_activate(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    ch = temp_character_object(test_char)
    ch.active = False
    pk = ch.save()
    response = test_client.post('/character/activate', json={"pk":ch.pk}).json
    log.info(response)
    character = test_client.get(f'/character/{ch.pk}').json
    pk = character['results']['pk']
    assert ch.active
    after_test_cleanup()

def test_deactivate(test_client, test_char):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    ch = temp_character_object(test_char)
    ch.active = True
    ch.save()
    response = test_client.post('/character/deactivate', json={"pk":ch.pk}).json
            
    assert not ch.active
    after_test_cleanup()