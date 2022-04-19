from src.models.compendium import Compendium
from src.lib import debug_print

class TestCompendium:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search()
        #debug_print(results=results)
        assert results.get('results')

        results = Compendium.search("fire")
        #debug_print(results=results)
        assert results.get('results')
        
        results = Compendium.search("djydkdkuculkc")
        #debug_print(results=results)
        assert not results['results']
        
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Compendium.count() > 0

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result =  Compendium.random()
        #debug_print(results=result)
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')