from src.models.compendium.monster import Monster

class TestMonster:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search(**test_search_endpoints['monster'])
        assert results.get('error') is None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Monster.count() > 0