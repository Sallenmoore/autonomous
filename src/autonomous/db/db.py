#external imports
import os
import pathlib

from autonomous.db.table import Table
from autonomous import log

class Database:

    def __init__(self, path):
        """
        [create an interface for your database]
        """
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path = path + "/"
        self.db_path = f'{pathlib.Path().resolve()}{path}{os.environ.get("DB_NAME", "tables")}'
        #log(self.db_path)
        os.path.isdir(self.db_path) or os.makedirs(self.db_path)
        self.tables = {}

    def get_table(self, table="default"):
        """
            opens the table from the file, which clears any changed data
        """
        if not self.tables.get(table):
            self.tables[table] = Table(table, path=self.db_path)
        return self.tables[table]


auto_db = Database(os.environ.get("AUTO_TABLE_PATH", "/"))
