from src.models.compendium.item import Item
from src.lib import debug_print

class TestItem:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search(**test_search_endpoints['item'])
        debug_print(results=results)
        assert results.get('results') is not None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Item.count() > 0