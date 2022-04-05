from src.models.monster import Monster

class TestMonster:

    def test_random(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.random()
        assert results.get('error') is None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Monster.count() > 0