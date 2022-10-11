import pytest
from selflib.logger import log
from selflib.db.db import Database

class Record:
    def __init__(self):
        self.pk = None
        self.num = 5
        self.name="buh"
        self.col = [1, 2, 3]
    
@pytest.fixture
def db_tester():
    db = Database()
    table = db.get_table("Record")
    yield table
    table.clear()

def test_db_create(db_tester):
    t = Record()
    t.pk = db_tester.update(t)
    assert t.pk > 0

def test_db_read(db_tester):
    t = Record()
    t.pk = db_tester.update(t)
    log(t.pk)
    obj = db_tester.get(t.pk)
    log(obj.pk)
    assert t.pk == obj.pk
    assert obj.num == 5

def test_db_update(db_tester):
    t = Record()
    t.pk = db_tester.update(t)
    obj = db_tester.get(t.pk)
    assert t.pk == obj.pk
    assert obj.num == 5
    obj.num = 6
    pk = db_tester.update(obj)
    obj = db_tester.get(pk)
    assert obj.pk == pk
    assert obj.num == 6

def test_db_delete(db_tester):
    t = Record()
    t.pk = db_tester.update(t)
    obj = db_tester.get(t.pk)
    db_tester.delete(obj.pk)
    assert not db_tester.get(t.pk)

def test_db_search(db_tester):
    t = Record()
    db_tester.update(t)
    t.pk = None
    t.name = "change"
    db_tester.update(t)
    t.pk = None
    t.name = "another change"
    db_tester.update(t)
    results = db_tester.search(name="buh")
    assert len(results) == 1
    assert results[0].name == "buh"
    results = db_tester.search(name="change")
    assert len(results) == 2
    assert all("change" in r.name for r in results)
    results = db_tester.search(name="ang")
    assert len(results) == 2
    assert all("change" in r.name for r in results)
    results = db_tester.search(name="xxx")
    assert len(results) == 0
    
def test_db_all(db_tester):
    num = 10
    t = Record()
    for i in range(num):
        db_tester.update(t)
        t.pk = None
    assert len(db_tester.all()) == num