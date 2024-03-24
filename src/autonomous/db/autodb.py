"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""

import glob
import os
import subprocess
import urllib.parse
from datetime import datetime

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
        self.connect_str = f"mongodb://{username}:{password}@{host}:{port}"
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

    def dbdump(self, directory):
        """
        dumps the database to a json file
        """
        datetime_string = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        command_str = f'mongodump --uri="{self.connect_str}" --archive="{directory}/dbbackup-{datetime_string}.archive"'
        result = subprocess.Popen(command_str, shell=True).wait()
        log(result, command_str)

    def dbload(self, directory):
        """
        loads the database from a json file
        """
        files = glob.glob(
            f"{directory}/dbbackup-*.archive"
        )  # replace with your directory path

        # Find the file with the most recent timestamp
        latest_file = max(files, key=os.path.getctime)
        log(latest_file)
        command_str = (
            f'mongorestore --uri="{self.connect_str}" --archive="{latest_file}"'
        )
        result = subprocess.Popen(command_str, shell=True).wait()
        log(result, command_str)
