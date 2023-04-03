# from autonomous import log
from pathlib import Path

from autonomous.db.autodb import Database


class RecordTest:
    def __init__(self, **kwargs):
        self.pk = None
        self.num = 5
        self.name = "buh"
        self.__dict__.update(kwargs)


class TestDatabase:
    db = Database().get_table("RecordTest")

    def test_db_table(self):
        db = Database("tests")
        obj = Path(db.db_path)
        assert obj.exists()

    def test_db_create(self):
        self.db.clear()
        t = RecordTest()
        t.pk = self.db.save(t.__dict__)
        assert t.pk > 0

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
        obj = RecordTest(**model)
        assert obj.pk == t.pk
        assert t.num == obj.num == 6

    def test_db_delete(self):
        self.db.clear()
        t = RecordTest()
        self.db.save(t.__dict__)
        assert not self.db.delete(t.pk)
