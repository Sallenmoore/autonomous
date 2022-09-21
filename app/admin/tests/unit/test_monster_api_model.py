from models.monster import Monster

from sharedlib.logger import log

class TestMonsterAPIModel: 


    def test_monster_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.all()
        assert [results]
        for r in results:
            assert r.name
        
    def test_monster_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Monster.search(name="Fire")
        assert results
        for r in results:
            assert "fire" in r.name.lower()

