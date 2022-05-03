from src.models.campaign.monster import Monster


class TestMonster:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search()
        
        assert results.get('results')

        results = Monster.search(name="Aatxe")
        
        assert results.get('results')

        results = Monster.search("djydkdkuculkc")
        
        assert not results['results']
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Monster.count() > 0

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result =  Monster.random()
        
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')