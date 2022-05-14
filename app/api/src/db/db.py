#external imports
from tinydb import TinyDB, Query
from tinydb.table import Document
import pathlib
import os
import logging

log = logging.getLogger()

class Table:
    
    def __init__(self, table):
        """
        [summary]
        """
        self.table = TinyDB(table)

    def update(self, object):
        """
        [summary]
        """
        #log.debug(f"{object}")
        if object.get('pk'):
            return self.table.update(object, doc_ids=[object.get('pk')])
        return self.table.insert(object)

    def delete(self, id):
        """
        [summary]
        """ 
        self.table.remove(Query().doc_id == id)

    def search(self, **kwargs):
        """
        [summary]
        """
        q = Query().fragment(kwargs)
        return self.table.search(q)

    def all(self):
        return self.table.all()
    
    def __str__(self):
        return self.table.name


class Database():

    def __init__(self):
        """
        [create an interface for your database]
        """
        self.db_path = f'{pathlib.Path().resolve()}/{os.environ.get("DB_NAME", "tables")}'
        os.path.isdir(self.db_path) or os.makedirs(self.db_path)
        self.tables = {}
            
    def get_table(self, table="configuration"):
        """
            opens the table from the file, which clears any changed data
        """
        if not self.tables.get(table):
            self.tables[table] = Table(f"{self.db_path}/{table}.json")
        return self.tables[table]



