from src.models.compendium.item import Compendium

class TestCompendium:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search(**test_search_endpoints['compendium'])
        assert results.get('error') is None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Compendium.count() > 0