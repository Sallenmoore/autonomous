from src.models.campaign.monster import Monster


class TestMonster:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search()
        
        assert results

        results = Monster.search(name="Aatxe")
        
        assert results

        results = Monster.search("djydkdkuculkc")
        
        assert not results
        
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
        
        assert result[0]['name']
        assert len(result) == 1