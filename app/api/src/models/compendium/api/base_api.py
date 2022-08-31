

import requests
from urllib.parse import urlencode
import logging
log = logging.getLogger()

class BaseAPI:
    """
    _summary_

    Returns:
        _type_: _description_
    """
    
    @classmethod
    def _request(cls, urls, full_api_results=False):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        results = {"results":{}, "num_responses":0}
        for url in urls:
            log.info(f"requesting {url}")
            response = requests.get(url)
            try:
                response = response.json()
                results['results'][url] = response
                results['num_responses'] += 1
            except requests.JSONDecodeError as e:
                results['results'][url] =  [f"ERROR: [{url}]"]
            else:
                log.debug(f"results: {results}")
                if full_api_results:
                    while response.get('next'):
                        log.debug(f"retrieving next page of results: {response.get('next')}")
                        response = requests.get(response.get('next')).json()
                        results['results'][url].update(results)
                        log.debug(f"results: {results}")
            
        return results
    
    @classmethod
    def build_general_search_url(cls, api_url, search_term):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        if api_url.endswith('/'):
            api_url = api_url[:-1]
        #general search:/search/?text=<value>
        return f"{api_url}/search/?text={search_term}"

    @classmethod
    def build_resource_search_url(cls, api_url, resource, search_term):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """ 
        if api_url.endswith('/'):
            api_url = api_url[:-1]
        return f"{api_url}/{resource}/?search={search_term}"

    @classmethod
    def build_resource_all_url(cls, api_url, resource):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """
        if api_url.endswith('/'):
            api_url = api_url[:-1]
        
        return f"{api_url}/{resource}"

    @classmethod
    def get(cls, api_url, resource, search_term):
        """
        _summary_

        _extended_summary_

        Args:
            resources (_type_, optional): _description_. Defaults to None.
            full_api_results (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        url = cls.build_resource_search_url(api_url, r, search_term)
        return cls._request([url], full_api_results = True)

    @classmethod
    def search(cls, api_url, resources, search_term, full_api_results=False):
        """
        _summary_

        _extended_summary_

        Args:
            resources (_type_, optional): _description_. Defaults to None.
            full_api_results (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        # check if it is a search request
        urls = []
        if (not resources) or "search" in resources:
            urls.append(cls.build_general_search_url(api_url, search_term))
        else:
            resources = resources if isinstance(resources, (list, tuple)) else [resources]
            for r in resources:
                urls.append(cls.build_resource_search_url(api_url, r, search_term))
        result = cls._request(urls, full_api_results = full_api_results)
        return result

    @classmethod
    def all(cls, api_url, resources):
        """
        _summary_

        _extended_summary_

        Args:
            refresh (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        urls = []
        resources = resources if isinstance(resources, (list, tuple)) else [resources]
        for r in resources:
            urls.append(cls.build_resource_all_url(api_url, r))
        
        return cls._request(urls, full_api_results=True)
        