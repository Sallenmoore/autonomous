from src.models import Compendium
from src.db.model import Model

class Item(Model, Compendium):
    resource = ["magicitems", "weapons"]

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
