from models.proxymodeltest import ProxyModelTest
from models.modeltest import ModelTest
from config import Config
import pytest

def model_tester():
    mt = ModelTester()
    mt.name = "Test"
    mt.status = "Testing..."
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.keystore = {"test1":"value1", "test2":"value2"}
    mt.save()
    yield mt
    mt.delete()

def proxymodel_tester():
    mt = ProxyModelTest()
    mt.name = "ProxyTest"
    mt.status = "Proxy Testing..."
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.keystore = {"test1":"value1", "test2":"value2"}
    return mt

def test_model_create():
    pmt = proxymodel_tester()
    pmt.save()
    assert pmt.pk > 0

def test_model_read():
    pmt = proxymodel_tester()
    pmt.save()
    pm = ProxyModelTest.get(pmt.pk)
    assert pm.pk == pmt.pk

def test_model_update():
    pmt = proxymodel_tester()
    pmt.save()
    assert pmt.name == "ProxyTest"
    pmt.name = "Change"
    upk = pmt.save()
    assert upk == pmt.pk
    pm = ProxyModelTest.get(upk)
    assert pm.name == "Change"

def test_model_delete():
    pmt = proxymodel_tester()
    pmt.save()
    pmt.delete()
    pm = ProxyModelTest.get(pmt.pk)
    assert not pm

    results = ProxyModelTest().all()
    [o.delete() for o in results]
    results = ProxyModelTest().all()
    assert not results

def test_search():
    pmt = proxymodel_tester()
    pmt.save()
    pmt.pk = None
    pmt.name = "Change"
    pmt.save()
    pmt.pk = None
    pmt.name = "Another Change"
    pmt.save()
    results = ProxyModelTest.search(name="ProxyTest")
    assert all(r.name == "ProxyTest" for r in results)
    results = ProxyModelTest.search(name="change")
    assert all("Change" in r.name for r in results)
    
def test_all():
    num = 10
    for i in range(num):
        proxymodel_tester().save()
    assert len(ProxyModelTest.all()) >= num

    results = ProxyModelTest().all()
    [o.delete() for o in results]
    results = ProxyModelTest().all()
    assert not results
        