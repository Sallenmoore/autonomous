from src.models.spell import Spell
from src.lib import debug_print

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
        #debug_print(all=result)
        for r in results:
            assert r.name

        results = Spell.search("fire")
        #debug_print(fire=result)
        for r in results:
            assert r.name

        results = Spell.search("hjkdgflsadk")
        #debug_print(hjkdgflsadk=results)
        assert not results