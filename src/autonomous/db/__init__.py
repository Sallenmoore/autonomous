import os

from .autodb import AutoDB

db = AutoDB(os.environ.get("AUTO_TABLE_PATH", "/"))
