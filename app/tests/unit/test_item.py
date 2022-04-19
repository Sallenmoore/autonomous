from src.models.item import Item
from src.lib import debug_print
class TestItem:

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.random()
        #debug_print(test_results=results)
        assert results.name
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search()
        #debug_print(all=result)
        for r in results:
            assert r.name

        results = Item.search("fire")
        #debug_print(fire=result)
        for r in results:
            assert r.name

        results = Item.search("hjkdgflsadk")
        #debug_print(hjkdgflsadk=result)
        assert not results