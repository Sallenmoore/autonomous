from src.models import Compendium

from flask import (
    current_app
)
import requests

class Character(Compendium):

    @classmethod
    def search(cls, **search_terms):
        """
        _summary_
        """
        return {}