from src.models import Compendium

from flask import (
    current_app
)

class Item(Compendium):
    search_results = None
    resource = ["magicitems", "weapons"]
