import os

from redis_om import get_redis_connection


# Singleton pattern
class Database:
    instance = get_redis_connection()

    @classmethod
    def save(cls, key, value):
        cls.instance.set(key, value)

    @classmethod
    def delete(cls, key):
        cls.instance.delete(key)

    @classmethod
    def all(cls):
        return cls.instance.keys("*")

    @classmethod
    def get(cls, key):
        return cls.instance.get(key)

    @classmethod
    def search(cls, key):
        return cls.instance.keys(key)

    @classmethod
    def cleardb(cls):
        return cls.instance.flushdb()
