# from autonomous import log
import timeit

import pytest

from autonomous import log
from autonomous.db.autodb import Database


class SubRecordTest:
    attributes = {"pk": None, "name": "buh"}

    def __init__(self, **kwargs):
        self.pk = None
        self.__dict__.update(kwargs)


class RecordTest:
    attributes = {"pk": None, "num": 5, "name": "buh", "sub": None}

    def __init__(self, **kwargs):
        self.pk = None
        self.num = 5
        self.name = "buh"
        self.sub = None
        self.__dict__.update(kwargs)


class TestDatabasePerformance:
    db = Database(
        host="localhost",
        port="10001",
    ).get_table("RecordTest", RecordTest.attributes)

    def test_db_search(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        for name in ["change", "stevenallenmoore@gmail.com", "g723578,/@$#%$"]:
            t.name = name
            t.pk = None
            self.db.save(t.__dict__)
        time = timeit.timeit(lambda: self.db.search(name="change"), number=10)
        print(f"\nsearch 'name' time: {time}")
        time = timeit.timeit(lambda: self.db.search(name="g723578,/@$#%$"), number=10)
        print(f"\nsearch 'not found' time: {time}")
