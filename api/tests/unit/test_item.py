from src.models.compendium.item import Item

class TestItem:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search(**test_search_endpoints['item'])
        assert results.get('error') is None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Item.count() > 0