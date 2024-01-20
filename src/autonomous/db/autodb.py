"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import os
import urllib.parse

import pymongo

from autonomous import log

from .table import Table


class Database:
    """
     _summary_

    _extended_summary_

    :return: _description_
    :rtype: _type_
    """

    def __init__(
        self,
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", 27017),
        password=os.getenv("DB_PASSWORD"),
        username=os.getenv("DB_USERNAME"),
        db=os.getenv("DB_DB"),
    ):
        """
        create an interface for your database
        """
        # log(self.username, self.password)
        username = urllib.parse.quote_plus(str(username))
        password = urllib.parse.quote_plus(str(password))
        # log(f"mongodb://{username}:{password}@{host}", port=int(port))
        self.db = pymongo.MongoClient(
            f"mongodb://{username}:{password}@{host}", port=int(port)
        )[db]
        self.tables = {}

    def get_table(self, table="default", schema=None):
        """
        opens the table from the file, which clears any changed data
        """
        if not self.tables.get(table):
            self.tables[table] = Table(table, schema, self.db)
        return self.tables[table]
