# Local Imports
from autonomous.response import Response
from autonomous.logger import log


# Third Party Imports
import requests

#template
from .test_app.app.api.app import app
from .test_app.app.api.models.modeltest import ModelTest
from .test_app.app.app.models.submodeltest import SubModelTest

def add_test_model():
    mt = ModelTest()
    mt.name = "ProxyTest"
    mt.status = "Proxy Testing..."
    mt.thing_date = datetime.now()
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.keystore = {"test1": "value1", "test2": "value2"}
    mt.sub= SubModelTest(subname="SubTest", subnumber=100)
    mt.__dict__.update(kwargs)
    mt.save()
    return mt

@pytest.fixture()
def client():
    app.config['TESTING'] = True
    return app.test_client()

def clear_test_models():
    ModelTest.delete_all()

def test_response_packaging():
    pmt = model_tester()
    result = Response.package(data=pmt)
    log(result)
    result = Response.unpackage(result)
    assert results == results
    clear_test_models()

def test_model_get(client):
    # Configure the requests
    [add_test_model() for i in range(3)]
    response = client.get(f"/modeltest/45")
    assert not response.json['result']
    models = ModelTest.all()
    for model in models:
        response = client.get(f"/modeltest/{model.pk}")
        results = Response.unpackage(response.json, ModelTest)
        for result in results:
            assert result.name == model.name
            assert result.status == model.status
            assert result.collection == model.collection
            assert result.value == model.value
            assert result.keystore == model.keystore
            assert result.sub.subname == model.sub.name
            assert result.sub.number == model.sub.number
    clear_test_models()

def test_proxy_get():
    # Configure the requests
    for i in range(3):
        model = add_test_model()
        result = requests.get(f"localhost:7357/read/{model.pk}")
        assert result.name == model.name
        assert result.status == model.status
        assert result.collection == model.collection
        assert result.value == model.value
        assert result.keystore == model.keystore
        assert result.sub.subname == model.sub.name
        assert result.sub.number == model.sub.number
    clear_test_models()  

def test_model_create(client):
    # Configure the requests
    [add_test_model() for i in range(3)]

    assert len(ModelTest.all()) == 3

    clear_test_models()

def test_proxy_create():
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    requests.get("localhost:7357/create")

    clear_test_models() 

def test_model_update(client):
    # Configure the requests
    
    for i in range(3):
        model = add_test_model()
        model.name = f"Updated-{model.name}"
        results = Response.package(data=model)
        response = client.post(f"/modeltest/update/", json=results)

    assert all("Updated" in model.name for model in ModelTest.all())

    clear_test_models()

def test_proxy_update():
    # Configure the requests
    [add_test_model() ]
    for i in range(3):
        model = add_test_model()
        updated = requests.get(f"localhost:7357/update/{model.pk}").json()
        result = Response.unpackage(updated)
        assert result.name == "updated"
        assert result.sub.name == "updated"

    clear_test_models() 


def test_model_delete(client):
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    for model in ModelTest.all():
        results = Response.package(data=model.pk)
        response = client.post(f"/modeltest/delete", json=results)

    assert not ModelTest.all()

    clear_test_models()

def test_proxy_delete():
    # Configure the requests
    for i in range(3):
        model = add_test_model() 
        requests.get(f"localhost:7357/delete/{model.pk}")
        assert ModelTest.get(model.pk) == None
    clear_test_models() 



def test_search(client):
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    results = Response.package(data={"name":"ProxyTest"})
    response = client.post(f"/modeltest/search", json=results)
    results = Response.unpackage(response)
    assert len(results['results']) == 3
    assert all(m.name == "ProxyTest" for m in results['results'])

    clear_test_models()

def test_proxy_search():
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    requests.get("localhost:7357/search")

    clear_test_models()

def test_all(client):
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    response = client.get(f"/modeltest/all")
    results = Response.unpackage(response)
    assert len(results['results']) == 3
    assert all(m.name == "ProxyTest" for m in results['results'])

    clear_test_models()

def test_proxy_all():
    # Configure the requests
    [add_test_model() for i in range(3)]
    
    requests.get("localhost:7357/all")

    clear_test_models()


