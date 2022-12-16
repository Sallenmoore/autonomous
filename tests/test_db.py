from autonomous import log
from autonomous.db.db import Database
from pathlib import Path

import pytest

class RecordTest:
    def __init__(self, **kwargs):
        self._auto_pk = None
        self._auto_model = self.__class__
        self.num =  5
        self.name = "buh"
        self.__dict__.update(kwargs)
        
db = Database("tests").get_table("RecordTest")

def start_test():
    db.clear()
    return RecordTest()

#############################   TESTS FOR db.py   #############################

def test_db_table():
    db = Database("tests")
    obj = Path(db.db_path)
    assert obj.exists()

def test_db_create():
    t = start_test()
    t._auto_pk = db.update(t)
    assert t._auto_pk > 0

def test_db_all():
    t = start_test()
    t._auto_pk = db.update(t)
    assert len(db.all()) == 1

def test_db_read():
    t = start_test()
    t._auto_pk = db.update(t)
    model = db.get(t._auto_pk)
    obj = RecordTest(**model)
    #log(obj)
    assert obj._auto_pk == t._auto_pk
    assert obj.num == 5

def test_db_search():
    tester = start_test()
    tester.name = "change"
    db.update(tester)
    assert len(db.search(name="buh")) == 0
    assert len(db.search(name="change")) == 1
    assert len(db.search(name="xxx")) == 0

def test_db_update():
    tester = start_test()
    db.update(tester)
    tester.num = 6
    db.update(tester)
    model = db.get(tester._auto_pk)
    #log(type(model), model)
    obj = RecordTest(**model)
    assert obj._auto_pk == tester._auto_pk
    assert tester.num == obj.num == 6

def test_db_delete():
    tester = start_test()
    assert not db.delete(tester._auto_pk)