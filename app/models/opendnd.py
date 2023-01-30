from urllib.parse import quote_plus, urlencode

import requests


class OpenDnDAPI:
    """
    _summary_

    - Filtering: api.open5e.com/monsters/?challenge_rating=3
    - Resource Searches: https://api.open5e.com/monsters/?search=fir
    - General Search: https://api.open5e.com/search/?text=fire

    Returns:
        _type_: _description_
    """

    API_URL = "https://api.open5e.com/"

    @classmethod
    def _request(cls, url):
        """
        request from each object API resource

        Returns:
            _type_: _description_
        """
        results = {}
        response = requests.get(url)
        try:
            response = response.json()
        except requests.JSONDecodeError as e:
            results[url] = [f"ERROR [{url}]: {e}"]
        else:
            results = response["results"]
            while response.get("next"):
                response = requests.get(response.get("next")).json()
                results.update(response["results"])
        return results

    @classmethod
    def get(cls, url):
        """
        _summary_

        _extended_summary_

        Args:
            resources (_type_, optional): _description_. Defaults to None.
            full_api_results (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        url = f"{cls.API_URL}/{url}"
        result = cls._request(url)
        return result

    def find(self, search=None, resource=None, **kwargs):
        if search:
            params = {"search": search}
        else:
            params = kwargs
        params = urlencode(f"{params}")
        if resource == "spells":
            url = f"spells/?{params}"
        elif resource == "monsters":
            url = f"monsters/?{params}"
        elif resource == "races":
            url = f"races/?{params}"
        elif resource == "classes":
            url = f"classes/?{params}"
        elif resource == "magicitems":
            url = f"magicitems/?{params}"
        elif resource == "weapons":
            url = f"weapons/?{params}"
        elif resource == "armor":
            url = f"armor/?{params}"
        else:
            url = f"search/?text={params}"

        result = self.get(url)
        return result

    def find_monster(self, search=None, **kwargs):
        return self.find(search=search, resource="monsters", **kwargs)

    def find_spell(self, search=None, **kwargs):
        return self.find(search=search, resource="monsters", **kwargs)

    def find_weapon(self, search=None, **kwargs):
        return self.find(search=search, resource="monsters", **kwargs)

    def find_armor(self, search=None, **kwargs):
        return self.find(search=search, resource="monsters", **kwargs)

    def find_magicitem(self, search=None, **kwargs):
        return self.find(search=search, resource="monsters", **kwargs)
