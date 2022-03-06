#external imports
from tinydb import TinyDB, Query

#python modules
import os

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
        Object = Query()
        self.table.upsert(object, Object._id == object['_id'])

    def delete(self, object):
        """
        [summary]
        """
        Object = Query()
        self.table.remove(Object._id == object['_id'])


class Database():

    def __init__(self):
        """
        [create an interface for your database]
        """
        self.db_name = os.environ.get("DB_NAME", "tables")
        self.tables = {}
            
    def get_table(self, table="configuration"):
        """
            opens the table from the file, which clears any changed data
        """
        if not self.tables.get(f"{self.db_name}/{table}.json"):
            self.tables[table] = Table(table)
        return self.tables[table]



