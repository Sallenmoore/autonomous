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
        if not object.get('pk'):
            object['pk'] = self.table.insert(object)
        return self.table.update(object, doc_ids=[object['pk']])

    def delete(self, id):
        """
        [summary]
        """ 
        #log.debug(id)
        result = self.table.remove(doc_ids=[id,])
        log.debug(result)
        return result

    def search(self, **kwargs):
        """
        [summary]
        """
        q = Query().fragment(kwargs)
        return self.table.search(q)

    def get(self, id):
        """
        [summary]
        """
        return self.table.get(doc_id=id)

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



