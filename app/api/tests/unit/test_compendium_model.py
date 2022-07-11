from src.models.compendium import Compendium


class TestCompendium:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search()
        
        assert results.get('results')

        results = Compendium.search("fire")
        
        assert results.get('results')
        
        results = Compendium.search("djydkdkuculkc")
        
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
        
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')