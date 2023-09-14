"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import os

import redis

from autonomous import log

from .table import Table


class Database:
    """
     _summary_

    _extended_summary_

    :return: _description_
    :rtype: _type_
    """

    port = os.getenv("REDIS_PORT", 6379)
    host = os.getenv("REDIS_HOST", "redis")
    password = os.getenv("REDIS_PASSWORD")
    username = os.getenv("REDIS_USERNAME")
    db = os.getenv("REDIS_DB")
    decode_responses = os.getenv("REDIS_DECODE")

    def __init__(self):
        """
        create an interface for your database
        """
        #log(self.username, self.password)
        options = {}

        if Database.username:
            options["username"] = Database.username
        if Database.password:
            options["password"] = Database.password
        if Database.decode_responses:
            options["decode_responses"] = Database.decode_responses

        self.db = redis.Redis(
            host=Database.host,
            port=Database.port,
            db=Database.db,
            **options,
        )
        self.tables = {}

    def get_table(self, table="default", schema=None):
        """
        opens the table from the file, which clears any changed data
        """
        if not self.db.exists(table):
            self.db.json().set(table, "$", {})

        self.tables[table] = Table(table, attributes=schema, db=self.db)
        return self.tables[table]
