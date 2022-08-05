from src.models.compendium.spell import Spell


class TestSpell:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search()
        
        assert results

        results = Spell.search(name="Acid Arrow")
        
        assert results

        results = Spell.search("djydkdkuculkc")
        
        assert not results
        
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
        
        assert result[0]['name']
        assert len(result) == 1