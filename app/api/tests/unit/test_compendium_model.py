from models.compendium import Compendium, Item, Spell, PlayerClass, Monster

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

    def test_all_items(self):
        Compendium.item_search("Boots", refresh=True)
        Compendium.item_search("Club", refresh=True)
        Compendium.item_search("Scale", refresh=True)
        
        results = Item.all()
        
        assert filter(lambda x: x.name == "Scale mail", results)
        assert filter(lambda x: x.name == "Club", results)
        assert filter(lambda x: x.name == "Scale mail", results)

    def test_search_item(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.item_search("Fire", refresh=True)
        assert results


    def test_all_monsters(self):
        results = Compendium.monster_search("Young", refresh=True)
        results = Monster.all()
        assert filter(lambda x: x.name == "Young Spinosaurus", results)

    def test_search_monster(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.monster_search("Fire", refresh=True)
        assert results


    def test_all_spells(self):
        results = Compendium.spell_search("Acid", refresh=True)
        results = Spell.all()
        assert filter(lambda x: x.name == "Acid Arrow", results)

    def test_search_spells(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Compendium.spell_search("Fire", refresh=True)
        assert results

    def test_all(self):
        results = PlayerClass.all()
        assert filter(lambda x: x.name == "Barbarian", results)

    def test_list(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = PlayerClass.list(refresh=True)
        assert "Barbarian" in results