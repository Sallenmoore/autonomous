from src.models.compendium.item import Compendium
from src.lib import debug_print

class TestCompendium:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search(**test_search_endpoints['compendium'])
        #debug_print(results=results)
        assert results.get('results') is not None
        
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Compendium.count() > 0