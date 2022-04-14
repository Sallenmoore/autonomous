from src.models import Compendium

from flask import (
    current_app
)

class Monster(Compendium):
    search_results = None
    resource = ["monsters"]