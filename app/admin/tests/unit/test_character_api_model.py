from models.character import Character
import pytest
from sharedlib.logger import log


# @pytest.fixture(scope='session', autouse=True)
# def db_cleanup():
#     yield
#     # Will be executed after the last test
#     results = Character.all()
#     for r in results:
#         log.warning(r)
#         if (not hasattr(r, "player_class")) or r.player_class == "Test":
#             r.delete()

class TestCharacterAPIModel: 
    testchar = {
        "name":"Test Character", 
        "image_url":"test.png",
        "player_class":"Test",
        "history":"Test",
        "hp":100,
        "status":"None",
        "inventory":["Test Item #1", "Test Item #2"]
    }


    def test_character_create(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        assert ch.name
        assert ch.player_class
        
    def test_character_save(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        assert ch.name
        assert ch.player_class
        
        result = ch.save()
        log(ch)
        assert type(ch.pk) is int
        
        r = Character.get(ch.pk)
        log(r)
        assert all([r.name == "Test Character", r.player_class == "Test"])

    def test_character_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        results = Character.all()

        count = 0
        for r in results:
            log(r)
            if all([r.name == "Test Character", r.player_class == "Test"]):
                count += 1
        assert count

    def test_update(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        assert type(ch.pk) == int
        pk = ch.pk
        ch = Character.get(pk)
        assert pk == ch.pk
        ch.status = "Dead"
        ch.save()
        ch = Character.get(ch.pk)
        assert pk == ch.pk
        assert ch.status == "Dead"

        #update all test objects with new hp
        results = [r for r in Character.all() if all([r.name == "Test Character", r.player_class == "Test"])]
        for r in results:
            log(r.pk)
            r.hp = 50
            r.status = "Dead"
            r.inventory.append("Test Item #3")
            r.save()
            log(f"{r}")

        #verify update    
        results = [r for r in Character.all() if all([r.name == "Test Character", r.player_class == "Test"])]
        for r in results:
            if all([r.name == "Test Character", r.player_class == "Test"]):
                assert r.hp == 50
                assert r.status == "Dead"
                assert "Test Item #3" in r.inventory
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        results = Character.search(name="Test Character")
        assert results
        for r in results:
            assert r.name == "Test Character" and r.player_class == "Test"

    def test_delete(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        results = Character.all()
        verify = []
        for r in results:
            if all([r.name == "Test Character", r.player_class == "Test"]):
                verify.append(r)
        assert verify
        for r in verify:
            r.delete()
        results = Character.all()
        assert not [r for r in results if all([r.name == "Test Character", r.player_class == "Test"])]

