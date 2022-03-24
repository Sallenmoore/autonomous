import urllib
import json

from flask import current_app


def test_search(test_client, test_search_term, endpoint="search"):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    url = f'/compendium/search/{urllib.parse.urlencode(test_search_term)}'
    current_app.logger.debug(f'REQUEST URL: {url}')
    response = test_client.get(url)
    data = response.data.decode('utf-8')
    current_app.logger.debug(f'RESPONSE DATA: {data}')
    result = json.loads(data)
    results = result.get("results")
    assert response.status_code == 200
    assert result 
    return result