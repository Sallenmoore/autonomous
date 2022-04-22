from src.lib import debug_print

import requests
from urllib.parse import urlencode

class DnDAPI:
    """
    _summary_

    Returns:
        _type_: _description_
    """
    API_URL = "https://api.open5e.com/"

    @classmethod
    def _response(cls, results):
        """
        _summary_

        Args:
            results (_type_): _description_

        Returns:
            _type_: _description_
        """
        packaged_result = {"results":[], "count":0, "next":[], 'api_urls':[]}
        #debug_print(results)
        for url, r in results.items():
            #debug_print(url=url, r=r.keys())
            packaged_result["results"] += r.get('results', [])
            if r.get('next'):
                packaged_result['next'] += [r['next']]
            packaged_result["count"] += r['count'] if r.get('count') else len(r.get("results", []))
            packaged_result['api_urls'] += [url]
        return packaged_result
    
    @classmethod
    def _request(cls, urls):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        results = {}
        for url in urls:
            results[url] = requests.get(url)
            try:
                results[url] = results[url].json()
            except requests.JSONDecodeError as e:
                results[url] = {'error':f"[{url}] not found"}
        #debug_print(results=results)
        return cls._response(results)
    
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
        term = search_terms.pop('search', "")
        url = f"{cls.API_URL}{resource}/?search={term}"
        #debug_print(url=url)
        final_url = f"{url}&{urlencode(search_terms)}" if search_terms else url
        debug_print(final_url=final_url)
        return final_url

    @classmethod
    def _build_keyword_search_url(cls, resource, **search_terms):
        """
        _summary_

        Args:
            resource (_type_): _description_

        Returns:
            _type_: _description_
        """
        #debug_print(search_terms=search_terms)
        search_terms.pop('search', None)
        return f"{cls.API_URL}{resource}/?{urlencode(search_terms)}"

    @classmethod
    def api_request(cls, resources=None, **search_terms):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        if (not resources) or "search" in resources:
            term = search_terms.pop('search', '')
            url = cls._build_general_search_url(search_term=term, **search_terms)
            #debug_print(url=url)
            return cls._request([url])
        
        urls = []
        for r in resources:
            if search_terms.get('search'):
                urls.append(cls._build_resource_search_url(r, **search_terms))
            else:
                urls.append(cls._build_keyword_search_url(r, **search_terms))
        return cls._request(urls)