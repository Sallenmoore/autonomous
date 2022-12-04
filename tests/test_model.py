import pytest
from datetime import datetime
from autonomous import log
from autonomous.model.model import Model 
from autonomous.model.basemodel import AutoModel


class SubModelTest(Model):

    def autoattributes(self):
        #log(self)
        return {
            "name": str,
            "number": int,
        }

class ModelTest(Model):

    def autoattributes(self):
        #log(self)
        return {
            "name": str,
            "status": SubModelTest,
            "thing_date": datetime,
            "collection": list,
            "value": int,
            "nothing": str,
            "keystore": dict,
        }

def clear_db():
    ModelTest.delete_all()
    SubModelTest.delete_all()

def make_model():
    subobj = SubModelTest(name="TestSub", number=1)
    log(subobj)
    mt = ModelTest(
        name = "Test",
        status = subobj,
        collection = ["one", "two", "three"],
        value = 100,
        nothing = None,
        keystore = {"test1": "value1", "test2": "value2"},
        invalid_attribute = "This should not be saved",
        thing_date = datetime.today(),
    )
    mt.save()
    return mt

def start_test():
    clear_db()
    return make_model()

def test_create():
    mt = start_test()
    assert mt.save()
    #log(mt)
    assert mt.pk
    assert mt.name == "Test"
    assert isinstance(mt.status, (SubModelTest, AutoModel))
    assert isinstance(mt.collection, list)
    assert isinstance(mt.value, int)
    assert isinstance(mt.keystore, dict)

def test_read():
    mt = start_test()
    resultA = ModelTest.get(mt.pk)
    assert resultA.pk == mt.pk
    assert resultA.name == "Test"
    assert isinstance(resultA.collection, list)
    assert isinstance(resultA.value, int)
    assert isinstance(resultA.keystore, dict)
    assert resultA.thing_date.day == datetime.today().day
    assert resultA.thing_date.hour == datetime.today().hour

def test_all():
    mt = start_test()
    mt = make_model()
    mt = make_model()
    results = ModelTest.all()
    #log(results)
    pks = [r.pk for r in results]
    assert pks
    assert pks == list(set(pks))

def test_attributes_type():
    mt = start_test()
    mt.value = None
    mt.save()
    #log(resultC)
    clone_mt = ModelTest.get(mt.pk)
    #log(resultC)
    assert clone_mt.pk == mt.pk
    assert not mt.value
    assert not hasattr(mt, "invalid_attribute")

def test_update():
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

def test_delete():
    mt = start_test()
    log(mt)
    assert not mt.delete()
    assert not ModelTest.get(mt.pk)

def test_search():
    mt = start_test()
    mt = make_model()
    mt = make_model()
    results = ModelTest.search(name=mt.name)
    assert len(results)
    assert all(r.name in mt.name for r in results)

def submodel_create():
    mt = start_test()
    model_testerA = model_create()
    model_testerA.collection += [SubModelTest(name="I am test. Hear me test.") for i in range(3)]
    #log(model_testerA, LEVEL="DEBUG")
    model_testerA.save()
    assert len(model_testerA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in model_testerA.collection)
    return model_testerA


def submodel_read(mt):
    mt = start_test()
    resultA = ModelTest.get(mt.pk)
    model_testerA.collection = [SubModelTest(name="I am test. Hear me test.") for i in range(3)]
    #log(resultA.collection, LEVEL="INFO")
    assert len(resultA.collection) == 3
    assert all(r.name == "I am test. Hear me test." for r in resultA.collection)

def submodel_update(mt):
    mt = start_test()
    mt.status.name = "Changed"
    mt.save()
    result = ModelTest.get(mt.pk)
    assert result.status.name == "Changed"
