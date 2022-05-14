from src.models.campaign.character import Character

import logging
log = logging.getLogger()

class TestCharacter:

    def test_create(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        test_char = Character(
            image_url = "test",
            name = "test",
            player_class = "test",
            history = "test",
            hp = 100,
            status = "test",
            inventory = ["test", "test"],
        )

        assert test_char.image_url == "test"
        assert test_char.name == "test"
        assert test_char.player_class == "test"
        assert test_char.history == "test"
        assert test_char.hp == 100
        assert test_char.status == "test"
        assert test_char.inventory == ["test", "test"]


    def test_save(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """

        test_char = Character(
            image_url = "test",
            name = "test",
            player_class = "test",
            history = "test",
            hp = 100,
            status = "test",
            inventory = ["test", "test"],
        )
        test_char.save()

        results = Character.find(name="test")
        assert len(results)


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
