import pytest
from datetime import datetime
from autonomous import log
from autonomous.model.model import Model


class SubModelTest(Model):
    @classmethod
    def auto_attributes(cls):
        return {
            "name": str,
            "number": int,
        }

class ModelTest(Model):
    @classmethod
    def auto_attributes(cls):
        return {
            "name": str,
            "status": SubModelTest,
            "thing_date": datetime,
            "collection": list,
            "value": int,
            "nothing": str,
            "keystore": dict,
        }


def model_create():
    mt = ModelTest(
        name = "Test",
        status = SubModelTest(name="TestSub", number=1),
        collection = ["one", "two", "three"],
        value = 100,
        nothing = None,
        keystore = {"test1": "value1", "test2": "value2"},
        invalid_attribute = "This should not be saved",
        thing_date = datetime.today(),
    )
    #log(mt)
    mt.save()
    assert mt.save()
    #log(mt)
    assert mt.pk
    assert mt.name == "Test"
    assert isinstance(mt.status, SubModelTest)
    assert isinstance(mt.collection, list)
    assert isinstance(mt.value, int)
    assert isinstance(mt.keystore, dict)
    return mt



def model_read(mt):
    resultA = ModelTest.get(mt.pk)
    assert resultA.pk == mt.pk
    assert resultA.name == "Test"
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.value, int)
    assert isinstance(resultA.keystore, dict)
    assert resultA.thing_date.day == datetime.today().day
    assert resultA.thing_date.hour == datetime.today().hour

def model_all():
    results = ModelTest.all()
    #log(results)
    pks = [r.pk for r in results]
    assert pks
    assert pks == list(set(pks))

def model_attributes_type(mt):
    mt.value = None
    mt.save()
    #log(resultC)
    clone_mt = ModelTest.get(mt.pk)
    #log(resultC)
    assert clone_mt.pk == mt.pk
    assert not mt.value
    assert not hasattr(mt, "invalid_attribute")

def model_update(mt):
    mt.nothing = "Changed"
    mt.save()
    resultA = ModelTest.get(mt.pk)
    #log(resultA)
    assert resultA.nothing == "Changed"

    model_testerA.collection.append("Changed")
    model_testerA.keystore["added"] = "Changed"
    model_testerA.save()
    resultA = ModelTest.get(model_testerA.pk)
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.keystore, dict)
    assert "Changed" in resultA.collection
    assert "added" in resultA.keystore
    assert resultB.keystore['added'] == "Changed"

def model_delete(mt):
    assert not mt.delete()
    assert not ModelTest.get(mt.pk)

def model_search(mt):
    results = ModelTest.search(name=mt.name)
    assert len(results)
    assert all(r.name in mt.name for r in results)

def submodel_create():
    model_testerA = model_create()
    model_testerA.collection += [SubModelTest(name="I am test. Hear me test.") for i in range(3)]
    #log(model_testerA, LEVEL="DEBUG")
    model_testerA.save()
    assert len(model_testerA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in model_testerA.collection)
    return model_testerA


def submodel_read(mt):
    #log(model_testerA, LEVEL="DEBUG")
    resultA = ModelTest.get(mt.pk)
    #log(resultA.collection, LEVEL="INFO")
    #log(resultA.collection, LEVEL="INFO")
    assert len(resultA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in resultA.collection)

def submodel_update(mt):
    mt.status.name = "Changed"
    mt.save()
    result = ModelTest.get(mt.pk)
    assert result.status.name == "Changed"

def test_main():
    ModelTest.delete_all()
    SubModelTest.delete_all()
    objs = [model_create() for i in range(2)]
    
    model_all()

    all(model_read(obj) for obj in objs)

    all(model_attributes_type(obj) for obj in objs)
    
    model_search(obj)

    all(model_update(obj) for obj in objs)

    all(model_delete(obj) for obj in objs)
    
    objs = [submodel_create() for i in range(2)]

    all(submodel_read(obj) for obj in objs)

    all(submodel_update(obj) for obj in objs)