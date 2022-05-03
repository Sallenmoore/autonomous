from src.models.item import Item
class TestItem:

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.random()
        
        assert results.name
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search()
        
        for r in results:
            assert r.name

        results = Item.search("fire")
        
        for r in results:
            assert r.name

        results = Item.search("hjkdgflsadk")
        
        assert not results