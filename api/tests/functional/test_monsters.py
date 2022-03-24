import urllib
import json

from flask import current_app

def test_search(test_client, test_search_term):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    url = f'/monster/search{urllib.parse.urlencode(test_search_term)}'
    current_app.logger.debug(f'REQUEST URL: {url}')
    response = test_client.get(url)
    data = response.data.decode('utf-8')
    current_app.logger.debug(f'RESPONSE DATA: {data}')
    result = json.loads(data)
    results = result.get("results")
    assert response.status_code == 200
    assert result.get('error') is None
    return result

def test_random(test_client, test_search_term):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    url = '/monster/random'
    current_app.logger.debug(f'REQUEST URL: {url}')
    response = test_client.get()
    data = response.data.decode('utf-8')
    current_app.logger.debug(f'RESPONSE DATA: {data}')
    result = json.loads(data)
    results = result.get("results")
    assert response.status_code == 200
    assert result.get('error') is None 
    return result