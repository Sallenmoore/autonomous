import urllib
import json

from flask import current_app

def test_roll(test_client, die_str):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    url = f'/dice/roll/{urllib.parse.quote(die_str[0])}'
    current_app.logger.debug(f'REQUEST URL: {url}')
    response = test_client.get(url)
    data = response.data.decode('utf-8')
    current_app.logger.debug(f'RESPONSE DATA: {data}')
    result = json.loads(data)
    results = result.get("results")
    assert response.status_code == 200
    assert result.get('number') is die_str[1]
    assert result.get('result')