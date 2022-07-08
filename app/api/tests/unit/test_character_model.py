from src.models.campaign.character import Character

import logging
log = logging.getLogger()

class TestCharacter:

    test_char = Character(
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
        assert self.test_char.image_url == "test.png"
        assert self.test_char.name == "Test Character"
        assert self.test_char.player_class == "Test"
        assert self.test_char.history == "Test"
        assert self.test_char.hp == 100
        assert self.test_char.status == "None"
        assert self.test_char.inventory == ["Test Item #1", "Test Item #2"]


    def test_save(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """

        
        pk = self.test_char.save()
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
        log.info(results)
        for char in results:
            assert(char.name)
            log.info(char)
