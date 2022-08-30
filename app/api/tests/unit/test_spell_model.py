from src.models.compendium.spell import Spell


import logging
log = logging.getLogger()

class TestSpell:

    def test_all(self):
        results = Spell.search("Acid", refresh=True)
        results = Spell.all()
        assert filter(lambda x: x.name == "Acid Arrow", results)

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Spell.search("Fire", refresh=True)
        assert results