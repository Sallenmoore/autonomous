from src.models.monster import Monster

class TestMonster:

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.random()
        
        assert results.name
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search()
        
        for r in results:
            assert r.name

        results = Monster.search("fire")
        
        for r in results:
            assert r.name

        results = Monster.search("hjkdgflsadk")
        
        assert not results