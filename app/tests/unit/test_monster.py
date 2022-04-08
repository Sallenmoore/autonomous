from src.models.monster import Monster
from src.utilities import DEBUG_PRINT
class TestMonster:

    def test_random(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.random()
        DEBUG_PRINT(test_results=results)
        assert results.name
        
    def search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result = Monster.search()
        print(result)
        assert result

        result = Monster.search("fire")
        print(result)
        assert result

        result = Monster.search("hjkdgflsadk")
        print(result)
        assert result