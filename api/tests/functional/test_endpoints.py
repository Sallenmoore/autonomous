import urllib
import json
from tests import DEBUG_PRINT

def test_search(test_client, test_search_endpoints):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    for endpoints, terms in test_search_endpoints.items():
        url = urllib.parse.urlencode(terms) if terms else ''
        url = f'/{endpoints}/search{url}'
        DEBUG_PRINT(url=url)
        response = test_client.get(url)
        DEBUG_PRINT(response=response)
        data = response.data.decode('utf-8')
        result = json.loads(data)
        results = result.get("results")
        DEBUG_PRINT(results=results)
        assert response.status_code == 200
        assert result.get('error') is None
    return result

def test_random(test_client, test_random_endpoints):
    """
    _summary_

    Args:
        test_client (_type_): _description_
        test_search_terms (_type_): _description_
        endpoint (str, optional): _description_. Defaults to "search".

    Returns:
        _type_: _description_
    """
    for endpoint in test_random_endpoints:
        url = f'/{endpoint}/random'
        response = test_client.get(url)
        data = response.data.decode('utf-8')
        result = json.loads(data)
        results = result.get("results")
        assert response.status_code == 200
        assert result.get('error') is None 
    return result