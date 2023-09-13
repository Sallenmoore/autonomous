from autonomous import log

from ..db.redisdb import RedisDatabase
from .orm import ORM


class RedisORM(ORM):
    _database = RedisDatabase()
