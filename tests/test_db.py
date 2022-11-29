from autonomous import log
from autonomous.db.db import Database

import pytest

class RecordTest:
    def __init__(self, **kwargs):
        self._auto_pk = None
        self.num =  5
        self.name = "buh"
        self.__dict__.update(kwargs)
        
@pytest.fixture
def db():
    db = Database()
    table = db.get_table("RecordTest")
    yield table
    table.clear()

#############################   TESTS FOR db.py   #############################

def db_create(db):
    t = RecordTest()
    t._auto_pk = db.update(t)
    assert t._auto_pk > 0
    return t

def db_all(db):
    assert len(db.all()) == 2

def db_read(db, tester):
    log(tester._auto_pk)
    model = db.get(tester._auto_pk)
    log(type(model), model)
    obj = RecordTest(**model)
    #log(obj._auto_pk)
    assert obj._auto_pk == tester._auto_pk
    assert obj.num == 5
    return obj

def db_search(db, tester):
    tester.name = "change"
    db.update(tester)
    assert len(db.search(name="buh")) == 1
    assert len(db.search(name="change")) == 1
    assert len(db.search(name="xxx")) == 0

def db_update(db, tester):
    tester.num = 6
    db.update(tester)
    model = db.get(tester._auto_pk)
    log(type(model), model)
    obj = RecordTest(**model)
    assert obj._auto_pk == tester._auto_pk
    assert tester.num == obj.num == 6

def db_delete(db, tester):
    assert not db.delete(tester._auto_pk)

def test_main(db):
    obj = db_create(db)
    obj = db_create(db)
    obj = db_read(db, obj)
    db_all(db)
    db_search(db, obj)
    db_update(db, obj)
    db_delete(db, obj)