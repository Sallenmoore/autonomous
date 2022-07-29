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
        results = Compendium.search()
        log.info(results)
        assert len(results) > 0

        results = Compendium.search("fire")
        assert len(results) > 0
        
        results = Compendium.search("djydkdkuculkc")
        
        assert len(results) == 0
        
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Compendium.count() > 0

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result =  Compendium.random()
        
        assert result[0]['name']
        assert len(result) == 1