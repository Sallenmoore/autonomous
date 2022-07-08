from src.sharedlib.db.APIModel import APIModel

class TestAPIModel: 
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
        return all(r.image_url == "test.png",
                r.name == "Test Character",
                r.player_class == "Test",
                r.history == "Test",
            )

    def test_save(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        APIModel.save(self.testchar)
        results = APIModel.all()
        count = [r for r in results if self.verify_results(r)]
        assert len(count) >= 1

    def test_delete(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        APIModel.save(self.testchar)
        results = Character.all()
        results = [r for r in results if self.verify_results(r)]
        assert len(count) >= 1
        for r in results:
            if self.verify_results(r):
                Character.delete(r)
        results = Character.all()
        results = [r for r in results if self.verify_results(r)]
        assert len(results) == 0

    def test_update(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        APIModel.save(self.testchar)
        results = [r for r in Character.all() if self.verify_results(r)]
        assert len(results) >= 1
        for r in results:
            if self.verify_results(r):
                r.hp = 50
                r.status = "Dead"
                r.inventory.append("Test Item #3")
                r.save()
        results = [r for r in Character.all() if self.verify_results(r)]
        for r in results:
            if self.verify_results(r):
                assert r.hp == 50
                assert r.status == "Dead"
                assert r.inventory == ["Test Item #1", "Test Item #2", "Test Item #3"]
        
    def test_search(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        APIModel.save(self.testchar)
        results = [r for r in Character.search(name="Test Character") if self.verify_results(r)]
        assert len(results) >= 1

        for r in results:
            assert r.delete()