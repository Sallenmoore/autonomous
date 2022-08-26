from src.models.compendium import PlayerClass


class TestPlayerClass:

    def test_all(self):
        results = Monster.all()
        assert filter(lambda x: x.name == "Barbarian", results)

    def test_list(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        results = PlayerClass.list(refresh=True)
        assert "Barbarian" in results