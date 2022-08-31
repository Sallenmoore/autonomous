from models.character import Character
import logging
log = logging.getLogger()

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

    def verify_results(self, r):
        """
        _summary_

        Args:
            results (_type_): _description_

        Returns:
            _type_: _description_
        """
        return all([r.name == "Test Character", r.player_class == "Test"])

    def test_delete(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        results = Character.all()
        results = [r for r in results if self.verify_results(r)]
        assert results
        for r in results:
            if self.verify_results(r):
                Character.delete(r)
        results = Character.all()
        assert not [r for r in results if self.verify_results(r)]

    def test_save(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        result = ch.save()
        log.info(result)
        assert type(ch.pk) is int
        
        results = Character.all()
        log.info(results)
        assert any(r for r in results if self.verify_results(r))
        self.test_delete()

    def test_update(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        assert type(ch.pk) == int

        #update all test objects with new hp
        results = [r for r in Character.all() if self.verify_results(r)]
        for r in results:
            log.info(r.pk)
            r.hp = 50
            r.status = "Dead"
            r.inventory.append("Test Item #3")
            r.save()

        #verify update    
        results = [r for r in Character.all() if self.verify_results(r)]
        for r in results:
            if self.verify_results(r):
                assert r.hp == 50
                assert r.status == "Dead"
                assert r.inventory == ["Test Item #1", "Test Item #2", "Test Item #3"]
        self.test_delete()
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        ch = Character(**self.testchar)
        ch.save()
        results = [r for r in Character.search(name="Test Character") if self.verify_results(r)]
        assert results

        self.test_delete()

