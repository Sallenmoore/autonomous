# Local Imports
from autonomous.model.proxymodel import ProxyModel
from autonomous.utilities import package_response, unpackage_response
from autonomous.logger import log

# Third Party Imports
import pytest

# Standard library Imports
from unittest.mock import MagicMock, patch
import json

class SubModelTest(ProxyModel):
    API_URL = f"http://localhost/submodeltest"

class ProxyModelTest(ProxyModel):
    API_URL = f"http://localhost/proxymodeltest"


def proxymodel_tester(**kwargs):
    mt = ProxyModelTest()
    mt.name = "ProxyTest"
    mt.status = "Proxy Testing..."
    mt.collection = ["one", "two", "three"]
    mt.value = 100
    mt.keystore = {"test1": "value1", "test2": "value2"}
    mt.sub= SubModelTest()
    mt.__dict__.update(kwargs)
    return mt


@patch('autonomous.model.proxymodel.requests.post')
def test_model_create(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    
    serialize_mock = MagicMock()
    #log(pmt)
    serialize_mock.json.return_value = package_response(data=pmt)
    requests.return_value = serialize_mock

    pmt.save()

    requests.assert_called_with(
        'http://localhost/proxymodeltest/create',
        json={'data':pmt.serialize()},
        headers={'Content-type': 'application/json', 'Accept': 'text/plain'}
    )


@patch('autonomous.model.proxymodel.requests.get')
def test_model_get(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    serialize_mock.json.return_value = package_response(data=pmt)
    requests.return_value = serialize_mock

    pm = ProxyModelTest.get(1)

    requests.assert_called_with('http://localhost/proxymodeltest/1',)
    
@patch('autonomous.model.proxymodel.requests.get')
def test_submodel_get(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    serialize_mock.json.return_value = package_response(data=pmt)
    requests.return_value = serialize_mock

    pm = ProxyModelTest.get(1)
    assert type(pm.sub) == SubModelTest

    requests.assert_called_with('http://localhost/proxymodeltest/1',)

@patch('autonomous.model.proxymodel.requests.post')
def test_model_update(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    #log(pmt)
    serialize_mock.json.return_value = package_response(data=pmt)
    requests.return_value = serialize_mock

    pmt.save()

    requests.assert_called_with(
        'http://localhost/proxymodeltest/update',
        json={'data':pmt.serialize()},
        headers={'Content-type': 'application/json', 'Accept': 'text/plain'}
    )


@patch('autonomous.model.proxymodel.requests.post')
def test_model_delete(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    #log(pmt)
    serialize_mock.json.return_value = package_response(data=pmt.pk)
    requests.return_value = serialize_mock

    pmt.delete()

    requests.assert_called_with(
        'http://localhost/proxymodeltest/delete',
        json={'data':pmt.pk},
        headers={'Content-type': 'application/json', 'Accept': 'text/plain'}
    )


@patch('autonomous.model.proxymodel.requests.get')
def test_search(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    #log(pmt)
    serialize_mock.json.return_value = package_response(data=[pmt])
    requests.return_value = serialize_mock

    results = ProxyModelTest.search(name="ProxyTest")
    requests.assert_called_once_with('http://localhost/proxymodeltest/search?name=ProxyTest',)
    
    assert results
    assert results[0].name == "ProxyTest"


@patch('autonomous.model.proxymodel.requests.get')
def test_all(requests):
    # Configure the requests
    pmt = proxymodel_tester()
    pmt.pk = 1
    
    serialize_mock = MagicMock()
    #log(pmt)
    serialize_mock.json.return_value = package_response(data=[pmt])
    requests.return_value = serialize_mock

    results = ProxyModelTest.all()
    requests.assert_called_once_with('http://localhost/proxymodeltest/all',)
    
    assert results
    assert results[0].name == "ProxyTest"
