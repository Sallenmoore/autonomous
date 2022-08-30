from src.models.compendium import Compendium

import logging
log = logging.getLogger()

class TestCompendium:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search("Fire", refresh=True)
        assert results