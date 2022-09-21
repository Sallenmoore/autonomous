from models.campaign.character import Character

class TestCharacter:

    def test_char(self):
        return Character(
        name="Test Character", 
        image_url = "test.png",
        player_class = "Test",
        history = "Test",
        hp = 100,
        status = "None",
        inventory = ["Test Item #1", "Test Item #2"]
    )

    def test_create(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        pk = self.test_char().save()
        assert pk >= 0

        result = Character.get(pk)
         
        assert result.name == "Test Character"
        assert result.image_url == "test.png" 
        assert result.name == "Test Character"
        assert result.player_class == "Test" 
        assert result.history == "Test" 
        assert result.hp == 100 
        assert result.status == "None" 
        assert result.inventory == ["Test Item #1", "Test Item #2"]

    def test_all(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """

        results = Character.all()
        for char in results:
            assert(char.name)


    def test_read(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = Character.all()
        for char in results:
            result = Character.get(char.pk)
            assert result.pk == char.pk
            assert result.name
            assert result.player_class 


    def test_update(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        test = self.test_char()
        test.save()
        test.name = "Updated Test Character"
        test.save()
        test = Character.get(test.pk)
        assert test.name == "Updated Test Character"


    def test_delete(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        test = Character.search(player_class="Test")
        for r in test:
            r.delete()

        test = Character.search(player_class="Test")
        assert len(test) == 0

