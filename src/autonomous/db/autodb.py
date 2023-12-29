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

    def __init__(
        self,
        host=os.getenv("REDIS_HOST", "redis"),
        port=os.getenv("REDIS_PORT", 6379),
        password=os.getenv("REDIS_PASSWORD"),
        username=os.getenv("REDIS_USERNAME"),
        db=os.getenv("REDIS_DB"),
        decode_responses=os.getenv("REDIS_DECODE"),
    ):
        """
        create an interface for your database
        """
        # log(self.username, self.password)
        options = {}

        if username:
            options["username"] = username
        if password:
            options["password"] = password
        if decode_responses:
            options["decode_responses"] = decode_responses

        self.db = redis.Redis(
            host=host,
            port=port,
            db=db,
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
