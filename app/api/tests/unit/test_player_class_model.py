from src.models.compendium import PlayerClass

import logging
log = logging.getLogger()

class TestPlayerClass:

    def test_all(self):
        results = PlayerClass.all()
        assert filter(lambda x: x.name == "Barbarian", results)

    def test_list(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = PlayerClass.list(refresh=True)
        assert "Barbarian" in results