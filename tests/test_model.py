import pytest
from datetime import datetime
from autonomous.logger import log
from autonomous.model.model import Model


class SubModelTest(Model):
    attributes = {
        "name": str,
        "number": int,
    }

class ModelTest(Model):
    attributes = {
        "name": str,
        "status": SubModelTest,
        "thing_date": datetime,
        "collection": list,
        "value": int,
        "nothing": str,
        "keystore": dict,
    }


def model_tester():
    mt = ModelTest()
    mt.name = "Test"
    mt.status = SubModelTest(name="TestSub", number=1)
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.nothing = None
    mt.keystore = {"test1": "value1", "test2": "value2"}
    mt.invalid_attribute = "This should not be saved"
    mt.thing_date = datetime.today()
    mt.save()
    return mt


def test_model_create():
    model_testerA = model_tester()
    model_testerB = model_tester()
    #log(model_testerA)
    assert isinstance(model_testerA, ModelTest)
    assert model_testerA.pk > 0
    assert model_testerB.pk > model_testerA.pk
    assert model_testerA.name == "Test"
    assert isinstance(model_testerA.collection, list)
    assert isinstance(model_testerA.value, int)
    assert isinstance(model_testerA.keystore, dict)

def test_model_read():
    a_pk = model_tester().save()
    b_pk = model_tester().save()
    resultA = ModelTest.get(a_pk)
    resultB = ModelTest.get(b_pk)
    assert resultA.pk > 0
    assert resultB.pk > 0
    assert resultA.pk != resultB.pk
    assert resultA.name == "Test"
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.value, int)
    assert isinstance(resultA.keystore, dict)
    assert resultB.name == "Test"
    assert isinstance(resultB.collection, list)
    assert isinstance(resultB.value, int)
    assert isinstance(resultB.keystore, dict)
    assert resultB.thing_date.day == datetime.today().day
    assert resultB.thing_date.hour == datetime.today().hour
    
def test_model_attributes_type():
    resultC = model_tester()
    resultC.status = None
    resultC.save()
    #log(resultC)
    resultC = ModelTest.get(resultC.pk)
    #log(resultC)
    assert not resultC.status
    

def test_model_update():
    model_testerA = model_tester()
    model_testerB = model_tester()
    model_testerA.name = "Changed"
    model_testerB.name = "Altered"
    model_testerA.save()
    model_testerB.save()
    resultA = ModelTest.get(model_testerA.pk)
    resultB = ModelTest.get(model_testerB.pk)
    assert resultA.status != resultB.status
    assert resultA.name == "Changed"
    assert resultB.name == "Altered"

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
    #log(results)
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


def test_submodel_create():
    model_testerA = model_tester()
    model_testerB = model_tester()
    #log(model_testerA)
    assert isinstance(model_testerA, ModelTest)
    assert model_testerA.pk > 0
    assert model_testerB.pk > model_testerA.pk
    assert model_testerA.name == "Test"
    assert isinstance(model_testerA.collection, list)
    assert isinstance(model_testerA.value, int)
    assert isinstance(model_testerA.keystore, dict)


def test_submodel_read():
    a_pk = model_tester().save()
    b_pk = model_tester().save()
    resultA = ModelTest.get(a_pk)
    resultB = ModelTest.get(b_pk)
    assert resultA.pk > 0
    assert resultB.pk > 0
    assert resultA.pk != resultB.pk
    assert resultA.name == "Test"
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.value, int)
    assert isinstance(resultA.keystore, dict)
    assert resultB.name == "Test"
    assert isinstance(resultB.collection, list)
    assert isinstance(resultB.value, int)
    assert isinstance(resultB.keystore, dict)
    
def test_submodel_attributes_type():
    resultC = model_tester()
    resultC.status = None
    resultC.save()
    resultC = ModelTest.get(resultC.pk)
    log(resultC)
    assert not resultC.status
    

def test_submodel_update():
    model_testerA = model_tester()
    model_testerB = model_tester()
    model_testerA.status.name = "Changed"
    model_testerB.status.name = "Altered"
    model_testerA.save()
    model_testerB.save()
    resultA = ModelTest.get(model_testerA.pk)
    resultB = ModelTest.get(model_testerB.pk)
    assert resultA.status != resultB.status
    assert resultA.status.name == "Changed"
    assert resultB.status.name == "Altered"