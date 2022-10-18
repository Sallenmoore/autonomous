from autonomous.logger import log
from autonomous.db.db import Database

import pytest

class RecordTest:
    def __init__(self, **kwargs):
        self.pk = None
        self.num =  5
        self.name = "buh"
        self.__dict__.update(kwargs)

    def serialize(self):
        return vars(self)

    @classmethod
    def deserialize(cls, record):
        record['pk'] = int(record.get('pk'))
        record['num'] =  int(record.get('num'))
        record['stuff'] = record.get('stuff')
        return cls(**record)

@pytest.fixture
def db_tester():
    db = Database()
    table = db.get_table("RecordTest")
    yield table
    table.clear()

#############################   TESTS FOR db.py   #############################
def test_db_create(db_tester):
    t = RecordTest()
    t.pk = db_tester.update(t.serialize())
    assert t.pk > 0

def test_db_read(db_tester):
    t = RecordTest()
    t.pk = db_tester.update(t.serialize())
    log(t.pk)
    obj = RecordTest.deserialize(db_tester.get(t.pk))
    log(obj.pk)
    assert t.pk == obj.pk
    assert obj.num == 5

def test_db_update(db_tester):
    t = RecordTest()
    t.pk = db_tester.update(t.serialize())
    rec = db_tester.get(t.pk)
    obj = RecordTest.deserialize(rec)
    assert t.pk == obj.pk
    assert obj.num == 5
    obj.num = 6
    pk = db_tester.update(obj.serialize())
    obj = RecordTest.deserialize(db_tester.get(pk))
    assert obj.pk == pk
    assert obj.num == 6

def test_db_delete(db_tester):
    t = RecordTest()
    t.pk = db_tester.update(t.serialize())
    obj = RecordTest.deserialize(db_tester.get(t.pk))
    db_tester.delete(obj.pk)
    assert not db_tester.get(t.pk)

def test_db_search(db_tester):
    t = RecordTest()
    db_tester.update(t.serialize())
    t.pk = None
    t.name = "change"
    db_tester.update(t.serialize())
    t.pk = None
    t.name = "another change"
    db_tester.update(t.serialize())
    results = [RecordTest.deserialize(o) for o in db_tester.search(name="buh")]
    assert len(results) == 1
    assert results[0].name == "buh"
    results = [RecordTest.deserialize(o) for o in db_tester.search(name="change")]
    assert len(results) == 2
    assert all("change" in r.name for r in results)
    results = [RecordTest.deserialize(o) for o in db_tester.search(name="ang")]
    assert len(results) == 2
    assert all("change" in r.name for r in results)
    results = [RecordTest.deserialize(o) for o in db_tester.search(name="xxx")]
    assert len(results) == 0
    
def test_db_all(db_tester):
    num = 10
    t = RecordTest()
    for i in range(num):
        db_tester.update(t.serialize())
        t.pk = None
    assert len(db_tester.all()) == num