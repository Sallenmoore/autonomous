from src.models.spell import Spell


class TestSpell:

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.random()
        debug_print(test_results=results)
        assert results.name
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search()
        
        for r in results:
            assert r.name

        results = Spell.search("fire")
        
        for r in results:
            assert r.name

        results = Spell.search("hjkdgflsadk")
        
        assert not results