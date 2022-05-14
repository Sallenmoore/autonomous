
import urllib
import json

from flask import current_app

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