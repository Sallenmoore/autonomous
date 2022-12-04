import pytest
from datetime import datetime
import json
from autonomous import log
from autonomous.model.model import Model


class ResponseSubModelTest(Model):
    attributes = {
        "name": str,
        "number": int,
    }

class ResponseModelTest(Model):
    attributes = {
        "name": str,
        "status": ResponseSubModelTest,
        "thing_date": datetime,
        "collection": list,
        "value": int,
        "nothing": str,
        "keystore": dict,
    }
    
def clear_test_models():
    ModelTest.delete_all()

def model_tester():
    mt = ResponseModelTest()
    mt.name = "Test"
    mt.status = ResponseSubModelTest(name="TestSub", number=1)
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.nothing = None
    mt.keystore = {"test1": "value1", "test2": "value2"}
    mt.invalid_attribute = "This should not be saved"
    mt.thing_date = datetime.today()
    mt.save()
    assert mt.status
    return mt

def test_response_packaging():
    pmt = model_tester()
    result = response.package(data=[pmt])
    log(result)
    results = response.unpackage(result)
    assert results[0].pk == pmt.pk
    clear_test_models()