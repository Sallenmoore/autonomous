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
            

#################### TESTING ####################

def test_classes_list(test_client):
    """
    _summary_

    Returns:
        _type_: _description_
    """
    response = test_client.get('/compendium/classes_list')
    log.info(f'response: {response}')
    assert response.status_code == 200
    data = response.json
    log.info(f'data: {data}')
    assert not data['error']
    assert data['count'] > 0

def test_all(test_client):
    """
    _summary_

    Returns:
        _type_: _description_
    """

    response = test_client.get('/compendium/all')
    assert response.status_code == 200
    log.info(f'response: {response}')
    data = response.json
    log.info(f'data: {data}')
    assert not data['error']
    assert data['results']

def test_random(test_client):
    """
    _summary_

    Returns:
        _type_: _description_
    """

    response = test_client.get('/compendium/random')
    #log.debug(f'response: {response}')
    assert response.status_code == 200
    log.info(f'response: {response}')
    data = response.json
    log.info(f'data: {data}')
    assert not data['error']
    assert data['results']

def test_search(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'search': 'druid', 'spell':'fire', "monster":"fire", "item":"fire"}
    for k,v in search_terms.items():
        url = f'/compendium/search?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        log.info(f'result: {result}')
        assert result['results']

def test_monster(test_client):
    """
    _summary_

    Args:
        test_client (_type_): _description_

    Returns:
        _type_: _description_
    """
    search_terms = {'search': 'fire', 'search':'ice', "search":"none", "search":""}
    for k,v in search_terms.items():
        url = f'/compendium/monster?{urllib.parse.urlencode({k:v})}'
        result = test_client.get(url).json
        log.info(f'result: {result}')
        assert result['results']