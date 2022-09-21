from models.compendium import Compendium

from sharedlib.logger import log

class TestCompendiumAPIModel: 


    def test_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.all()
        assert [results]
        for r in results:
            assert r.name
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.search(name="Fire")
        assert results
        for r in results:
            assert "fire" in r.name.lower()

