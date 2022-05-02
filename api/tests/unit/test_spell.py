from src.models.compendium.spell import Spell
from src.lib import debug_print

class TestSpell:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search()
        #debug_print(results=results)
        assert results.get('results')

        results = Spell.search(name="Acid Arrow")
        #debug_print(results=results)
        assert results.get('results')

        results = Spell.search("djydkdkuculkc")
        #debug_print(results=results)
        assert not results['results']
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Spell.count() > 0

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result = Spell.random()
        #debug_print(results=result)
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')