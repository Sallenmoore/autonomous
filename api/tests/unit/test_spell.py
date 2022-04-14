from src.models.compendium.spell import Spell
from src.lib import debug_print

class TestSpell:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search(**test_search_endpoints['spell'])
        debug_print(results=results)
        assert results.get('results') is not None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Spell.count() > 0