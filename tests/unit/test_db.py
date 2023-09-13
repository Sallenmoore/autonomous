# from autonomous import log
from pathlib import Path

import pytest

from autonomous.db.autodb import Database


class RecordTest:
    attributes = {"pk": None, "num": 5, "name": "buh"}

    def __init__(self, **kwargs):
        self.pk = None
        self.num = 5
        self.name = "buh"
        self.__dict__.update(kwargs)


class TestDatabase:
    db = Database().get_table("RecordTest", RecordTest.attributes)

    def test_db_create(self):
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert t.pk

    def test_db_count(self):
        num = self.db.count()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert self.db.count() == num + 1

    def test_db_clear(self):
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        self.db.clear()
        assert self.db.count() == 0
        assert len(self.db.all()) == 0

    def test_db_all(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert len(self.db.all()) == 1

    def test_db_read(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        model = self.db.get(t.pk)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        # log(obj)
        assert obj.pk == t.pk
        assert obj.num == t.num

    def test_db_search(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        t.name = "change"
        self.db.save(t.__dict__)
        assert all(isinstance(model, dict) for model in self.db.search(name="change"))
        assert len(self.db.search(name="buh")) == 0
        assert len(self.db.search(name="change")) == 1
        assert len(self.db.search(name="xxx")) == 0

    def test_db_update(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        t.num = 6
        self.db.save(t.__dict__)
        model = self.db.get(t.pk)
        # log(type(model), model)
        assert isinstance(model, dict)
        obj = RecordTest(**model)
        assert obj.pk == t.pk
        assert t.num == obj.num == 6

    def test_db_delete(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        assert not self.db.delete(t.pk)
