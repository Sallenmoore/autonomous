# from autonomous import log
from pathlib import Path

import pytest

from autonomous import log
from autonomous.db.autodb import Database


class SubRecordTest:
    attributes = {"_id": None, "name": "buh"}

    def __init__(self, **kwargs):
        self._id = None
        self.__dict__.update(kwargs)


class RecordTest:
    attributes = {"_id": None, "num": 5, "name": "buh", "sub": None}

    def __init__(self, **kwargs):
        self._id = None
        self.num = 5
        self.name = "buh"
        self.sub = None
        self.__dict__.update(kwargs)


class TestDatabase:
    db = Database(
        host="localhost",
        port="10001",
    ).get_table("RecordTest", RecordTest.attributes)

    def test_db_create(self):
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        assert t._id

    def test_db_count(self):
        num = self.db.count()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        assert self.db.count() == num + 1

    def test_db_clear(self):
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        self.db.clear()
        assert self.db.count() == 0
        assert self.db.all() == []

    def test_db_all(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        assert len(self.db.all()) == 1

    def test_db_random(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        assert self.db.random()

    def test_db_read(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        model = self.db.get(t._id)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        assert obj._id == t._id
        assert obj.num == t.num

    def test_db_update(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        t.num = 6
        t._id = self.db.save(t.__dict__)
        model = self.db.get(t._id)
        log(type(model), model)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        assert obj._id == t._id
        assert t.num == obj.num == 6

    def test_db_delete(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        assert self.db.delete(t._id) == 1

    def test_db_search(self):
        self.db.clear()
        t = RecordTest()
        t._id = self.db.save(t.__dict__)
        t.name = "change"
        self.db.save(t.__dict__)
        # log(self.db.explain(name="change"))
        assert all(isinstance(model, dict) for model in self.db.search(name="change"))
        assert len(self.db.search(name="buh")) == 0
        assert len(self.db.search(name="change")) == 1
        assert len(self.db.search(name="xxx")) == 0
        t.name = "stevenallenmoore@gmail.com"
        self.db.save(t.__dict__)
        log(self.db.all())
        # breakpoint()
        result = self.db.search(name="stevenallenmoore@gmail.com")
        assert result[0]["name"] == "stevenallenmoore@gmail.com"

        t.name = "ste--venallenm#oor e@gmail.com"
        self.db.save(t.__dict__)
        result = self.db.search(name="ste--venallenm#oor e@gmail.com")
        assert result[0]["name"] == "ste--venallenm#oor e@gmail.com"

    # @pytest.mark.skip(reason="not implemented")
    # def test_subattribute_search(self):
    #     t = RecordTest()
    #     t._id = self.db.save(t.__dict__)
    #     sub = SubRecordTest()
    #     sub._id = self.db.save(sub.__dict__)
    #     t.sub = sub.__dict__
    #     self.db.save(t.__dict__)
    #     result = self.db.search(_id=sub._id)
    #     assert len(result) == 1
    #     result = self.db.search(_id=000)
    #     assert len(result) == 0
