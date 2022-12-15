import pytest
from autonomous import log
from autonomous.model.proxymodel import ProxyModel

from datetime import datetime

class ProxySubModelTest(ProxyModel):
    API_URL="http://localhost:7357/submodeltest"
    API_MODEL="SubModelTest"

class ProxyModelTest(ProxyModel):
    API_URL="http://localhost:7357/modeltest"
    API_MODEL="ModelTest"

def clear_db():
    ProxyModelTest.delete_all()
    ProxySubModelTest.delete_all()

def make_model():
    subobj = ProxySubModelTest(name="TestSub", number=1)
    #log(subobj)
    mt = ProxyModelTest(
        name = "test",
        sub = subobj,
        collection = ["one", "two", "three"],
        value = 100,
        nothing = None,
        keystore = {"test1": "value1", "test2": "value2"},
        timestamp = datetime.today(),
    )
    mt.save()
    return mt

def start_test():
    clear_db()
    return make_model()
  
def test_proxy_attributes():
    mt = ProxyModelTest()
    assert mt.name == None
    assert mt.sub == None 
    assert mt.collection == None
    assert mt.value == None
    assert mt.nothing == None
    assert mt.keystore == None
    assert mt.timestamp == None
    
def test_proxy_create():
    result = start_test()
    #log(result)
    model = ProxyModelTest.get(result.pk)
    assert result.name == model.name
    assert result.collection == model.collection
    assert result.value == model.value
    assert result.keystore == model.keystore
    assert result.sub.name == model.sub.name
    assert result.sub.number == model.sub.number

def test_read():
    result = start_test()
    assert ProxyModelTest.get(result.pk).pk == result.pk

def test_update():
    result = start_test()
    result.name = "updated"
    result.sub.name = "updated"
    result.save()
    result2=ProxyModelTest.get(result.pk)
    assert result.name == result2.name == "updated"
    assert result.sub.name == result2.sub.name == "updated"


def test_delete():
    result = start_test()
    result.delete()
    assert not ProxyModelTest.get(result.pk)


def test_search():
    result = start_test()
    assert ProxyModelTest.search(name="test")


def test_all():
    result = start_test()
    assert ProxyModelTest.all()

