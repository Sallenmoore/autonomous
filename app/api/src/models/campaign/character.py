from src.db.model import Model


class Character(Model):
    def model_attr(self) -> None:
        """
        [set object attributes]
        """
        self.image_url = str
        self.name = str
        self.player_class = str
        self.history = str
        self.hp = int
        self.status = str
        self.inventory = list

    def verify(self) -> bool:
        return True
