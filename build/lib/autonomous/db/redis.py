from functools import reduce
from .autodb import Database
# from redis import Redis

# https://redis.readthedocs.io/en/stable/redismodules.html#redis.commands.json.commands.JSONCommands.set


class RedisDB(Database):
    pass
    # def __init__(self):
    #     self.instance = Redis(host=os.getenv("REDIS_URL", default="localhost:6379"))

    # def save(self, key, table, value):
    #     self.instance.json().set(key, table, value)

    # def delete(self, key):
    #     self.instance.delete(key)

    # def all(self):
    #     return self.instance.keys("*")

    # def get(self, key):
    #     return self.instance.get(key)

    # def search(self, **kwargs):
    #     search_terms = []
    #     for k, v in kwargs.items():
    #         try:
    #             attr = getattr(self, k)
    #         except AttributeError:
    #             raise AttributeError(f"Model {self.__name__} has no attribute {k}")
    #         else:
    #             search_terms.append((attr << v))

    #     result = reduce(lambda x, y: x & y, search_terms)
    #     return self.find(result)

    # def cleardb(self):
    #     return self.instance.flushdb()
