import uuid
from datetime import datetime

import pytest

from autonomous import log
from autonomous.model.automodel import AutoModel


@pytest.fixture(autouse=True)
def run_before_and_after_tests():
    """Fixture to execute asserts before and after a test is run"""

    yield  # this is where the testing happens

    Model.table().flush_table()
    SubModel.table().flush_table()


class SubModel(AutoModel):
    # set model default attributes
    attributes = {"name": "", "age": None, "date": None}


class Model(AutoModel):
    # set model default attributes
    attributes = {
        "name": "",
        "age": None,
        "date": None,
        "auto": None,
        "autolist": [],
        "autodict": {},
        "autoobj": None,
    }


class TestAutomodel:
    def test_automodel_create(self):
        am = Model(name="test", age=10, date=datetime.now())
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()
        # assert am.pk

    def test_automodel_all_when_empty(self):
        results = Model.all()
        log(results)

    def test_automodel_save(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()

    def test_automodel_get(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()
        assert am.pk

        new_am = Model.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == am.name
        assert new_am.age == am.age
        new_am = Model.get(None)
        assert not new_am
        new_am = Model.get(-1)
        assert not new_am

    def test_automodel_update(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()

        am.name = "update"
        am.age = 99

        am.save()
        new_am = Model.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == "update"
        assert new_am.age == 99

    def test_automodel_search(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        new_am = Model.search(name="test")
        assert len(new_am) == 1
        assert new_am[0].pk == am.pk
        new_am = Model.search(age=10)
        assert len(new_am) == 1
        assert new_am[0].pk == am.pk

        am = Model(name="tester", age=9, date=datetime.now())
        am.save()
        new_am = Model.search(age=9)
        assert len(new_am) == 1
        assert new_am[0].pk == am.pk

        ams = Model.search(name="test")
        assert len(ams) == 2

    def test_automodel_delete(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()

        am.delete()
        new_am = Model.get(am.pk)

        assert not new_am

    def test_automodel_deserialize(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        am_dict = {
            "_automodel": am.model_name(),
            "_pk": am.pk,
        }
        result = Model._deserialize(am_dict)
        assert isinstance(result, Model)
        assert result.pk == am.pk
        assert result.name == am.name
        assert result.age == am.age
        assert result.date == am.date

        result = Model._deserialize([1, am_dict, 3])
        assert result[0] == 1
        assert result[2] == 3
        assert isinstance(result[1], Model)
        assert result[1].pk == am.pk
        assert result[1].name == am.name
        assert result[1].age == am.age

        result = Model._deserialize({"a": 1, "b": am_dict})
        assert result["a"] == 1
        assert isinstance(result["b"], Model)
        assert result["b"].pk == am.pk
        assert result["b"].name == am.name
        assert result["b"].age == am.age

        result = Model._deserialize({"a": 1, "b": [am_dict]})
        assert result["a"] == 1
        assert isinstance(result["b"][0], Model)
        assert result["b"][0].pk == am.pk
        assert result["b"][0].name == am.name
        assert result["b"][0].age == am.age

        result = Model._deserialize({"a": 1, "b": {"c": am_dict}})
        assert result["a"] == 1
        assert isinstance(result["b"]["c"], Model)
        assert result["b"]["c"].pk == am.pk
        assert result["b"]["c"].name == am.name
        assert result["b"]["c"].age == am.age

    def test_autoencoder_serialize(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()

        for i in range(3):
            subobj = SubModel(name=f"subtest{i}", age=11, date=datetime.now())
            subobj.save()
            am.autolist.append(subobj)
        testlist = am.autolist[:]

        result = am.serialize()

        for i, a in enumerate(result["autolist"]):
            log(a, type(a))
            assert isinstance(a, dict)
            assert testlist[i].model_name() == a["_automodel"]
            assert testlist[i].pk == a["_pk"]

        am.autodict = {a.pk: a for a in testlist}
        testdict = am.autodict.copy()
        result = am.serialize()
        # breakpoint()
        for k, a in result["autodict"].items():
            assert isinstance(a, dict)
            assert testdict[k].model_name() == a["_automodel"]
            assert testdict[k].pk == a["_pk"]
