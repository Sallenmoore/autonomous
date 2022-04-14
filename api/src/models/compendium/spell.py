from src.models import Compendium

from flask import (
    current_app
)

class Spell(Compendium):

    search_results = None
    resource = ["spells", "magicitems"]
