import os

from .autodb import Database

db = Database(os.environ.get("AUTO_TABLE_PATH", ""))
