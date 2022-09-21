from models.spell import Spell

from sharedlib.logger import log

class TestSpellAPIModel: 


    def test_spell_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.all()
        assert [results]
        for r in results:
            assert r.name
        
    def test_spell_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search(name="Fire")
        assert results
        for r in results:
            assert "fire" in r.name.lower()

