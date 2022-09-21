

import requests
from urllib.parse import urlencode

class BaseAPI:
    """
    _summary_

    Returns:
        _type_: _description_
    """
    
    @classmethod
    def _request(cls, urls):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        results = {"results":{}, "num_responses":0}
        for url in urls:
            response = requests.get(url)
            try:
                response = response.json()
            except requests.JSONDecodeError as e:
                results['results'][url] =  [f"ERROR [{url}]: {e}"]
            else:
                results['results'][url] = response
                results['num_responses'] += 1
                while response.get('next'):
                    next_response = requests.get(response.get('next')).json()
                    results['results'][response['next']] = next_response
                    results['num_responses'] += 1
                    response = next_response
        return results

    @classmethod
    def get(cls, api_url, resources):
        """
        _summary_

        _extended_summary_

        Args:
            resources (_type_, optional): _description_. Defaults to None.
            full_api_results (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        resources = resources if isinstance(resources, (list, tuple)) else [resources]
        urls = [f"{api_url.strip('/')}/{r}/" for r in resources]
        result = cls._request(urls)
        return result