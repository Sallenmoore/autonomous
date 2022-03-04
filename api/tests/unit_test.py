from models.compendium import Compendium

import pytest

class TestCompendium:
     
    def test_search_monsters(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_monsters(**{}).get("results"))
    
    def test_search_spells(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_spells(**{}).get("results"))
    
    
    def test_search_documents(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_documents(**{}).get("results"))
    
    
    def test_search_backgrounds(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_backgrounds(**{}).get("results"))
    
    
    def test_search_planes(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_planes(**{}).get("results"))
    
    
    def test_search_sections(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_sections(**{}).get("results"))
    
    
    def test_search_feats(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_feats(**{}).get("results"))
    
    
    def test_search_conditions(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_conditions(**{}).get("results"))
    
    
    def test_search_races(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_races(**{}).get("results"))
    
    
    def test_search_classes(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_classes(**{}).get("results"))
    
    
    def test_search_magicitems(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_magicitems(**{}).get("results"))
    
    
    def test_search_weapons(self, **search_terms):
        """
        _summary_
        """
        assert(Compendium.search_weapons(**{}).get("results"))
    
    
    def search(self, test_search_term):
        """
        _summary_
        """
        assert(Compendium.search(text="").get("results"))