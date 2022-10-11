#external imports
import os
import pathlib

from .table import Table


class Database:

    def __init__(self):
        """
        [create an interface for your database]
        """
        self.db_path = f'{pathlib.Path().resolve()}/{os.environ.get("DB_NAME", "tables")}'
        
        os.path.isdir(self.db_path) or os.makedirs(self.db_path)
        self.tables = {}

    def get_table(self, table="default"):
        """
            opens the table from the file, which clears any changed data
        """
        if not self.tables.get(table):
            self.tables[table] = Table(table, path=self.db_path)
        return self.tables[table]



