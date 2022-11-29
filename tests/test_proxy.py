import pytest
from autonomous import log
from autonomous.model.proxymodel import ProxyModel

from datetime import datetime

class SubModelTest(ProxyModel):
    API_URL="http://localhost:7359/submodeltest"

class ModelTest(ProxyModel):
    API_URL="http://localhost:7359/modeltest"


def make_model():
    m = ModelTest(
        name="test",
        sub=SubModelTest(name="subtest", number=2),
        collection=[1,2,3], 
        value = 754,
        nothing = None, 
        keystore = {'a':1, 'b':2},
        timestamp = datetime.now()
    )
    return m


def test_proxy_create():
    result = make_model().save()
    model = ModelTest.get(result)
    assert result.name == model.name
    assert result.status == model.status
    assert result.collection == model.collection
    assert result.value == model.value
    assert result.keystore == model.keystore
    assert result.sub.subname == model.sub.name
    assert result.sub.number == model.sub.number
    return response.package(data=result)

def test_read():
    make_model().save()
    for m in ModelTest.all():
        assert ModelTest.get(m.pk)
    return response.package(data=m)

def test_update():
    make_model().save()
    data=ModelTest.all()[0]
    data.name = "updated"
    data.sub.name = "updated"
    data.save()
    data2=ModelTest.get(pk)
    assert data.name == data2.name == "updated"
    assert data.sub.name == data2.sub.name == "updated"
    return response.package(data=ModelTest.get(pk))


def test_delete():
    make_model().save()
    for m in ModelTest.all():
        ModelTest.get(m.pk).delete()
    assert not ModelTest.all()
    return response.package(data=[])


def test_search():
    make_model().save()
    assert ModelTest.search(name="test")
    return {}


def test_all():
    make_model().save()
    assert ModelTest.all()
    return response.package(data=ModelTest.all())

