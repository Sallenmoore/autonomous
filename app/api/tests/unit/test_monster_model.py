from src.models.compendium import Monster

import logging
log = logging.getLogger()

class TestMonster:

    def test_all(self):
        results = Monster.search("Young", refresh=True)
        results = Monster.all()
        assert filter(lambda x: x.name == "Young Spinosaurus", results)

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search("Fire", refresh=True)
        assert results