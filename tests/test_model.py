import pytest
from datetime import datetime
from autonomous import log 
from autonomous.model.basemodel import AutoModel
from tests.apitester.app.api.models.modeltest import ModelTest
from tests.apitester.app.api.models.submodeltest import SubModelTest

def clear_db():
    ModelTest.delete_all()
    SubModelTest.delete_all()

def make_model():
    subobj = SubModelTest(name="TestSub", number=1)
    mt = ModelTest(
        name = "Test",
        sub = subobj,
        collection = ["one", "two", "three"],
        value = 100,
        nothing = None,
        keystore = {"test1": "value1", "test2": "value2"},
        timestamp = datetime.today(),
    )
    mt.save()
    #log(mt)
    return mt

def start_test():
    #clear_db()
    return make_model()

def test_model_attributes():
    mt = ModelTest()
    assert mt.name == None
    assert mt.sub == None 
    assert mt.collection == None
    assert mt.value == None
    assert mt.nothing == None
    assert mt.keystore == None
    assert mt.timestamp == None
    log(vars(ModelTest.__base__))
    attributes = ModelTest._Model__route_attributes()
    assert "_auto_model" in attributes['results']

def test_model_create():
    mt = start_test()
    assert mt.save()
    #log(mt)
    assert mt.pk
    assert mt.name == "Test"
    assert isinstance(mt.sub, (SubModelTest, AutoModel))
    assert isinstance(mt.collection, list)
    assert isinstance(mt.value, int)
    assert isinstance(mt.keystore, dict)

def test_model_read():
    mt = start_test()
    #breakpoint()
    resultA = ModelTest.get(mt.pk)
    assert resultA.pk == mt.pk
    assert resultA.name == "Test"
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.value, int)
    assert isinstance(resultA.keystore, dict)
    assert resultA.timestamp.day == datetime.today().day
    assert resultA.timestamp.hour == datetime.today().hour

def test_model_all():
    mt = start_test()
    mt = make_model()
    mt = make_model()
    results = ModelTest.all()
    #log(results)
    pks = [r.pk for r in results]
    assert pks
    assert pks == list(set(pks))

def test_model_attributes_type():
    mt = start_test()
    mt.value = None
    mt.save()
    #log(resultC)
    clone_mt = ModelTest.get(mt.pk)
    #log(resultC)
    assert clone_mt.pk == mt.pk
    assert not mt.value
    assert not hasattr(mt, "invalid_attribute")

def test_model_update():
    mt = start_test()
    mt.nothing = "Changed"
    mt.save()
    resultA = ModelTest.get(mt.pk)
    #log(resultA)
    assert resultA.nothing == "Changed"

    resultA.collection.append("Changed")
    resultA.keystore["added"] = "Changed"
    resultA.save()
    
    resultB = ModelTest.get(resultA.pk)
    assert isinstance(resultB.collection, list)
    assert isinstance(resultB.keystore, dict)
    assert "Changed" in resultB.collection
    assert "added" in resultB.keystore
    assert resultB.keystore['added'] == "Changed"

def test_model_delete():
    mt = start_test()
    #log(mt)
    assert not mt.delete()
    assert not ModelTest.get(mt.pk)

def test_model_search():
    mt = start_test()
    mt = make_model()
    mt = make_model()
    results = ModelTest.search(name=mt.name)
    assert len(results)
    assert all(r.name in mt.name for r in results)

def test_submodel_create():
    model_testerA = start_test()
    model_testerA.collection = [SubModelTest(name="I am test. Hear me test.") for i in range(3)]
    #log(model_testerA, LEVEL="DEBUG")
    model_testerA.save()
    assert len(model_testerA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in model_testerA.collection)
    return model_testerA


def test_submodel_read():
    mt = start_test()
    resultA = ModelTest.get(mt.pk)
    resultA.collection = [SubModelTest(name="I am test. Hear me test.") for i in range(3)]
    #log(resultA.collection, LEVEL="INFO")
    assert len(resultA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in resultA.collection)

def test_submodel_update():
    mt = start_test()
    mt.sub.name = "Changed"
    mt.save()
    result = ModelTest.get(mt.pk)
    assert result.sub.name == "Changed"

def test_submodel_search():
    mt = start_test()
    mt = make_model()
    mt = make_model()
    results = mt.sub.search(name='TestSub')
    log(mt, results)
    assert len(results)
    assert all(r.name in mt.sub.name for r in results)
    results = mt.sub.search(name='')
    assert not results
