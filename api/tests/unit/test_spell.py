from src.models.compendium.spell import Spell

class TestSpell:

    def test_search(self, test_search_endpoints):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search(**test_search_endpoints['spell'])
        assert results.get('error') is None
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Spell.count() > 0