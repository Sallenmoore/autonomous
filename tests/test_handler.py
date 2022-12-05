import pytest
from datetime import datetime
import jsonpickle
from autonomous import log
from autonomous.model.model import Model
from autonomous.model.basemodel import AutoModel
from autonomous.handler import AutoHandler, NetworkHandler


class HandlerSubModelTest(Model):
    def autoattributes(self): 
        return {
            "name": str,
            "number": int,
        }

class HandlerModelTest(Model):
    def autoattributes(self): 
        return {
        "name": str,
        "status": HandlerSubModelTest,
        "thing_date": datetime,
        "collection": list,
        "value": int,
        "nothing": str,
        "keystore": dict,
    }

def clear_db():
    HandlerModelTest.delete_all()
    HandlerSubModelTest.delete_all()

def make_model():
    subobj = HandlerSubModelTest(name="TestSub", number=1)
    mt = HandlerModelTest(
        name = "Test",
        status = subobj,
        collection = ["one", "two", "three"],
        value = 100,
        nothing = None,
        keystore = {"test1": "value1", "test2": "value2"},
        invalid_attribute = "This should not be saved",
        thing_date = datetime.today(),
    )
    return mt

def start_test():
    clear_db()
    return make_model()

def test_response_autohandle_flatten():
    pmt = start_test()
    result = jsonpickle.encode(pmt)
    log(result)
    assert result["_auto_pk"] == pmt.pk
    assert result["_auto_model"] == pmt._auto_model
    assert result["_auto_name"]
    assert result["_auto_name"]

def test_response_autohandle_restore():
    pmt = start_test()
    result = jsonpickle.decode(data)
    log(result)
    assert result["_auto_pk"] == pmt.pk
    assert result["_auto_model"] == pmt._auto_model
    assert result["_auto_name"]

def test_response_package():
    pmt = start_test()
    result = NetworkHandler.package(data=[pmt])
    log(result)
    assert results is dict
    assert results.get('results') is list
    assert results['results'][0]['_auto_pk'] == pmt.pk
    assert results['results'][0]['_auto_model'] == pmt._auto_model

def test_response_unpackage():
    pmt = start_test()
    data = {"results":jsonpickle.encode([pmt])}
    results = NetworkHandler.unpackage(data)
    assert results is list
    assert results[0]._auto_pk == pmt.pk
    assert results[0]._auto_model == pmt._auto_model


def test_response_get():
    result = NetworkHandler.get_request(url="localhost:3000")
    log(result)
    assert results[0]['id']

def test_response_post():
    result = NetworkHandler.post_request(url="localhost:3000", data={"id":2, "_auto_pk": 2, "_auto_model": "TestModel"})

