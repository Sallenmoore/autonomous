from datetime import datetime
import jsonpickle
from autonomous import log
from tests.apitester.app.api.models.modeltest import ModelTest
from tests.apitester.app.api.models.submodeltest import SubModelTest
from autonomous.handler import NetworkHandler

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
    return mt

def start_test():
    clear_db()
    return make_model()

def test_response_package():
    pmt = start_test()
    results = NetworkHandler.package(data=[pmt])
    log(results)
    assert isinstance(results, dict)
    assert isinstance(results.get('results'), str)
    assert '_auto_pk' in results['results']
    assert '_auto_model'in results['results']
    assert str(pmt.pk) in results['results']
    assert pmt._auto_model in results['results']

def test_response_unpackage():
    pmt = start_test()
    data = {"results":jsonpickle.encode([pmt])}
    results = NetworkHandler.unpackage(data)
    log(results)
    assert pmt.pk and results[0]._auto_pk
    assert results[0]._auto_pk == pmt.pk
    assert results[0]._auto_pk == pmt.pk
    assert results[0]._auto_model == pmt._auto_model

def test_response_get():
    pmt = start_test()
    result = NetworkHandler.get(url="http://localhost:7357/modeltest/all")
    log(result)
    assert result[0]._auto_pk == pmt.pk

def test_response_post():
    pmt = start_test()
    result = NetworkHandler.post(url="http://localhost:7357/modeltest/delete", data=pmt.pk)
    assert pmt._auto_model == result[0]._auto_model
    
