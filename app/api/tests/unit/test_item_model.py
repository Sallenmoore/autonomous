from src.models.compendium.item import Item


class TestItem:

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search()
        
        assert results

        results = Item.search(name="Adamantine Armor")
        
        assert results

        results = Item.search("djydkdkuculkc")
        
        assert not results
        
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
        
        assert result[0]['name']
        assert len(result) == 1