from src.models.item import Item
from src.lib import debug_print

class TestItem:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search()
        #debug_print(results=results)
        assert results.get('results')

        results = Item.search(name="Adamantine Armor")
        #debug_print(results=results)
        assert results.get('results')

        results = Item.search("djydkdkuculkc")
        #debug_print(results=results)
        assert not results['results']
        
    def test_count(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        assert Item.count() > 0

    def test_random(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        result =  Item.random()
        #debug_print(results=result)
        assert result.get('results')[0]['name']
        assert result.get('count') == 1
        assert not result.get('next')