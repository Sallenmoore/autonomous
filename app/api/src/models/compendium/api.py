

import requests
from urllib.parse import urlencode
import logging
log = logging.getLogger()

class DnDAPI:
    """
    _summary_

    Returns:
        _type_: _description_
    """
    API_URL = "https://api.open5e.com/"

    
    @classmethod
    def _request(cls, urls, full_api_results=False):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        results = {"results":[], "count":0}
        for url in urls:
            log.info(f"requesting {url}")
            response = requests.get(url)
            try:
                response = response.json()
                results['results'] += response['results']
                results['count'] += response['count']
            except requests.JSONDecodeError as e:
                results +=  [f"ERROR: [{url}] not found"]
            else:
                log.debug(f"results: {results}")
                if full_api_results:
                    while response.get('next'):
                        log.debug(f"retrieving next page of results: {response.get('next')}")
                        response = requests.get(response.get('next')).json()
                        results['results'] += response.get('results', [])
                        log.debug(f"results: {results}")
        return results
    
    @classmethod
    def _build_general_search_url(cls, search_term="", **kwargs):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        #general search:/search/?text=<value>
        url = f"{cls.API_URL}search/?text={search_term}"
        return f"{url}&{urlencode(kwargs)}" if kwargs else url

    @classmethod
    def _build_resource_search_url(cls, resource, **search_terms):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """
        #resource search:/<resource>/search/?text=<value>
        term = search_terms.pop('search', "")
        url = f"{cls.API_URL}{resource}/?search={term}"
        return f"{url}&{urlencode(search_terms)}" if search_terms else url

    @classmethod
    def _build_keyword_search_url(cls, resource, **search_terms):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """
        
        search_terms.pop('search', None)
        return f"{cls.API_URL}{resource}/?{urlencode(search_terms)}"

    @classmethod
    def api_request(cls, resources=None, full_api_results=False, **search_terms):
        """
        _summary_

        _extended_summary_

        Args:
            resources (_type_, optional): _description_. Defaults to None.
            full_api_results (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        if (not resources) or "search" in resources:
            term = search_terms.pop('search', '')
            url = cls._build_general_search_url(search_term=term, **search_terms)
            
            return cls._request([url])
        
        urls = []
        for r in resources:
            if search_terms.get('search'):
                urls.append(cls._build_resource_search_url(r, **search_terms))
            else:
                urls.append(cls._build_keyword_search_url(r, **search_terms))
        return cls._request(urls, full_api_results = full_api_results)