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
            

#################### TESTING ####################

def test_classes_list(test_client):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    response = test_client.get('/compendium/player_class/all')
    assert response.status_code == 200
    data = response.json
    assert not data['error']
    assert data['count'] > 0
    assert any(d['name'] == 'Warlock' for d in data['results'])

def test_search(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'name': 'druid', 'name':'fire', 'name':"", 'name':"dhfkashlA"}
    for k,v in search_terms.items():
        url = f'/compendium/search?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        assert all('name' in r for r in result['results'])

def test_monster(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'name': 'fire', 'name':'ice', 'name':"none", 'name':""}
    for k,v in search_terms.items():
        url = f'/compendium/monster/search?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        assert not result['error']

def test_monster_attributes(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    url = f'/compendium/monster/attributes'
    result = test_client.get(url).json
    assert "name" in result['results']

def test_item(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'name': 'fire', 'name':'ice', 'name':"none", 'name':""}
    for k,v in search_terms.items():
        url = f'/compendium/item/search?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        assert not result['error']

def test_item_attributes(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    url = f'/compendium/item/attributes'
    result = test_client.get(url).json
    assert "name" in result['results']

def test_spell(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'name': 'fire', 'name':'ice', 'name':"none", 'name':""}
    for k,v in search_terms.items():
        url = f'/compendium/spell/search?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        assert not result['error']

def test_spell_attributes(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    url = f'/compendium/spell/attributes'
    result = test_client.get(url).json
    assert "name" in result['results']