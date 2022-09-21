from models.compendium import Compendium, Item, Spell, PlayerClass, Monster
from sharedlib.logger import log

class TestCompendium:
    compendium_updated = True 

    def update_compendium(self):
        if not self.compendium_updated:
            Compendium.updatedb()
            self.compendium_updated = True

    def test_search(self):
        self.update_compendium()
        results = Compendium.search(name="Fire")
        #log(results)
        assert filter(lambda x: x.name == "Fireball", results)
        assert filter(lambda x: x.name == "Fire Imp", results)
        assert filter(lambda x: x.name == "Staff of Fire", results)
        
        results = Compendium.search(name="Ice Wall")
        #log(results)
        assert filter(lambda x: x.name == "Wall of Ice", results)
        
        results = Compendium.search(name="kdgaljsdhva;jk")
        #log(results)
        assert not results
        
        results = Compendium.all()
        assert filter(lambda x: x.name == "Club", results)
        assert filter(lambda x: x.name == "Scale mail", results)

    def test_search_items(self):
        self.update_compendium()
        results = Compendium.item_search(name="Fire")
        #log(results)
        found = False
        for item in results:
            if item.name == "Fireball":
                found = False
                break
            if item.name == "Fire Imp":
                found = False
                break
            if item.name == "Staff of Fire":
                found = True
        assert found
        
        results = Compendium.item_search(name="Necklace Fire")
        #log(results)
        assert filter(lambda x: x.name == "Necklace of Fireballs", results)
        
        results = Compendium.item_search(name="kdgaljsdhva;jk")
        #log(results)
        assert not results
        
        results = Compendium.item_all()
        assert filter(lambda x: x.name == "", results)
        assert filter(lambda x: x.name == "Scale mail", results)

    def test_search_monsters(self):
        self.update_compendium()
        results = Compendium.monster_search(name="Fire")
        #log(results)
        found = False
        for item in results:
            if item.name == "Fireball":
                found = False
                break
            if item.name == "Fire Imp":
                found = True
            if item.name == "Staff of Fire":
                found = False
                break
        assert found
        
        results = Compendium.monster_search(name="Fire Bat")
        #log(results)
        assert filter(lambda x: x.name == "Camazotz, Demon Lord Of Bats And Fire", results)
        
        results = Compendium.monster_search(name="kdgaljsdhva;jk")
        #log(results)
        assert not results
        
        results = Compendium.monster_all()
        assert filter(lambda x: x.name == "Young Spinosaurus", results)

    def test_search_spells(self):
        self.update_compendium()
        results = Compendium.spell_search(name="Fire")
        found = False
        for item in results:
            if item.name == "Fireball":
                found = True
            if item.name == "Fire Imp":
                found = False
                break
            if item.name == "Warhammer":
                log(item)
                found = False
                break
        assert found
        
        results = Compendium.spell_search(name="Fire Wall")
        #log(results)
        assert filter(lambda x: x.name == "Wall of Fire", results)
        
        results = Compendium.spell_search(name="kdgaljsdhva;jk")
        #log(results)
        assert not results
        
        results = Compendium.spell_all()
        assert filter(lambda x: x.name == "Acid Arrow", results)

    def test_playerclass_all(self):
        self.update_compendium()
        results = Compendium.class_list()
        assert filter(lambda x: x.name == "Barbarian", results)