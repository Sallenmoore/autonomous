from src.models.compendium.spell import Spell


class TestSpell:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search()
        
        assert results.get('results')

        results = Spell.search(name="Acid Arrow")
        
        assert results.get('results')

        results = Spell.search("djydkdkuculkc")
        
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
        
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')