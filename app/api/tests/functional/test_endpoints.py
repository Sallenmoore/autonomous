import urllib
import json



def test_all(test_client, test_search_endpoints):
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
        response = test_client.get(f'/{endpoints}/all')
        debug_print(f'/{endpoints}/all')
        data = response.data.decode('utf-8')
        debug_print(data)
        data = json.loads(data)
        assert response.status_code == 200
        assert data['results']
        assert data['count']

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
        response = test_client.get(url)
        data = response.data.decode('utf-8')
        
        assert response.status_code == 200

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
        
        assert response.status_code == 200
        assert result['count'] == 1
        assert len(result['results']) == 1