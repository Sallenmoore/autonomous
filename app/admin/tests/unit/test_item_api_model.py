from models.item import Item
from sharedlib.logger import log

class TestItemAPIModel: 


    def test_item_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.all()
        assert [results]
        for r in results:
            assert r.name
        
    def test_item_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search(name="Fire")
        assert results
        for r in results:
            assert "fire" in r.name.lower()

