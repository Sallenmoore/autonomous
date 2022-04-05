from src.models import Compendium

from flask import (
    current_app
)
import requests

class Item(Compendium):
    search_results = None
    resource = ["magicitems", "weapons"]
