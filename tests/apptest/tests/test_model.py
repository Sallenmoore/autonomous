import pytest
from autonomous.logger import log
from models.modeltest import ModelTest

def model_tester():
    mt = ModelTest()
    mt.name = "Test"
    mt.status = "Testing..."
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.nothing = None
    mt.keystore = {"test1":"value1", "test2":"value2"}
    mt.save()
    return mt

def test_model_create():
    model_testerA = model_tester()
    model_testerB = model_tester()
    log(model_testerA)
    assert isinstance(model_testerA, ModelTest)
    assert model_testerA.pk > 0
    assert model_testerB.pk > model_testerA.pk
    assert model_testerA.name == "Test"
    assert isinstance(model_testerA.collection, list)
    assert isinstance(model_testerA.value, int)
    assert isinstance(model_testerA.keystore, dict)

def test_model_read():
    model_testerA = model_tester()
    model_testerB = model_tester()
    resultA = ModelTest.get(model_testerA.pk)
    resultB = ModelTest.get(model_testerB.pk)
    assert resultA.pk > 0
    assert resultB.pk > 0
    assert resultA.pk != resultB.pk
    assert model_testerA.name == "Test"
    assert isinstance(model_testerA.collection, list)
    assert isinstance(model_testerA.value, int)
    assert isinstance(model_testerA.keystore, dict)
    assert model_testerB.name == "Test"
    assert isinstance(model_testerB.collection, list)
    assert isinstance(model_testerB.value, int)
    assert isinstance(model_testerB.keystore, dict)

def test_model_update():
    model_testerA = model_tester()
    model_testerB = model_tester()
    model_testerA.status = "Changed"
    model_testerB.status = "Altered"
    model_testerA.save()
    model_testerB.save()
    resultA = ModelTest.get(model_testerA.pk)
    resultB = ModelTest.get(model_testerB.pk)
    assert resultA.status != resultB.status
    assert resultA.status == "Changed"
    assert resultB.status == "Altered"
    
    model_testerA.collection.append("Changed")
    model_testerB.keystore["added"] = "Altered"
    model_testerA.save()
    model_testerB.save()
    resultA = ModelTest.get(model_testerA.pk)
    resultB = ModelTest.get(model_testerB.pk)
    assert isinstance(resultA.collection, list)
    assert isinstance(resultB.keystore, dict)
    assert "Changed" in resultA.collection
    assert "added" in resultB.keystore
    assert resultB.keystore['added'] == "Altered"

def test_delete():
    model_testerA = model_tester()
    pk = model_testerA.pk
    results = ModelTest.get(pk)
    log(results)
    results.delete()
    assert ModelTest.get(pk) == None
    results = ModelTest.all()
    [o.delete() for o in results]
    results = ModelTest.all()
    assert not results

def test_search():
    model_testerA = model_tester()
    results = ModelTest.search(name="Test")
    assert any(r.pk == model_testerA.pk for r in results)

def test_all():
    model_testerA = model_tester()
    model_testerB = model_tester()
    results = ModelTest.all()
    [o.delete() for o in results]
    results = ModelTest.all()
    assert not results