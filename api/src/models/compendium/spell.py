from src.models import Compendium
from src.lib.db.model import Model

class Spell(Model, Compendium):
    resource = ["spells", "magicitems"]

    #     def model_attr(self) -> None:
    #         """
    #         [set object attributes]
    #         """
    #         self.image_url = type
    #         self.player_name = type
    #         self.character = type
    #         self.player_class = type
    #         self.player_abilities = type

    #     def verify(self) -> bool:
    #         return True

    #     class Character:

    #         def verify(self) -> bool:
    #             return True