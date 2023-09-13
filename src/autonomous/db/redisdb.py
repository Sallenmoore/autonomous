"""
    _summary_

_extended_summary_

:return: _description_
:rtype: _type_
"""
import os

import redis

from autonomous import log

from .redistable import RedisTable


class RedisDatabase:
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
        log(self.username, self.password)
        options = {}

        if RedisDatabase.username:
            options["username"] = RedisDatabase.username
        if RedisDatabase.password:
            options["password"] = RedisDatabase.password
        if RedisDatabase.decode_responses:
            options["decode_responses"] = RedisDatabase.decode_responses

        self.db = redis.Redis(
            host=RedisDatabase.host,
            port=RedisDatabase.port,
            db=RedisDatabase.db,
            **options,
        )
        self.tables = {}

    def get_table(self, table="default", schema=None):
        """
        opens the table from the file, which clears any changed data
        """
        if not self.db.exists(table):
            self.db.json().set(table, "$", {})

        self.tables[table] = RedisTable(table, attributes=schema, db=self.db)
        return self.tables[table]
