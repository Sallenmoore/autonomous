from src.models.compendium.monster import Monster
from src.lib import debug_print

class TestMonster:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search(**test_search_endpoints['monster'])
        debug_print(results=results)
        assert results.get('results') is not None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Monster.count() > 0