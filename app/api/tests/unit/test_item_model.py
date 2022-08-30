from src.models.compendium.item import Item

import logging
log = logging.getLogger()

class TestItem:

    def test_all(self):
        results = Item.search("Boots", refresh=True)
        results = Item.all()
        assert filter(lambda x: x.name == "Scale mail", results)
        results = Item.search("Club", refresh=True)
        results = Item.all()
        assert filter(lambda x: x.name == "Club", results)
        results = Item.search("Scale", refresh=True)
        results = Item.all()
        assert filter(lambda x: x.name == "Scale mail", results)

    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Item.search("Fire", refresh=True)
        assert results