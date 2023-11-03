import uuid
from datetime import datetime
from typing import Any

import pytest

from autonomous import log
from autonomous.model.automodel import AutoModel


class SubModel(AutoModel):
    # set model default attributes
    name: str = ""
    age: int = 0
    date: datetime = None


class Model(AutoModel):
    # set model default attributes
    name: str = ""
    age: int = 0
    date: datetime = None
    auto: SubModel = None
    autolist: list[Any] = []
    autodict: dict = {}
    autoobj: SubModel = None


class RealModel(AutoModel):
    # set model default attributes
    name: str = ""


class ChildModel(RealModel):
    pass


# @pytest.mark.skip(reason="dumb test")
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

        am = RealModel(name="test")
        am.save()
        assert am.name == "test"

        # breakpoint()

        am = ChildModel(name="test")
        am.save()
        assert am.name == "test"
        assert am.model_name() == "test_automodel.ChildModel"

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

    def test_automodel_delete(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()

        am.delete()
        new_am = Model.get(am.pk)

        assert not new_am

    def test_automodel_deserialize(self):
        am = Model(name="test", age=10, date=datetime.now())
        pm = Model(name="test2", age=11, date=datetime.now())

        am.save()
        pm.save()

        result = am.deserialize()
        assert isinstance(result, Model)
        assert result.pk == am.pk
        assert result.name == am.name
        assert result.age == am.age
        assert result.date == am.date

        pm_dict = {"pk": pm.pk, "_automodel": pm.model_name()}
        am.autolist = [1, pm_dict, 3]
        log(am.autolist)
        result = am.deserialize()
        assert result.autolist[0] == 1
        assert result.autolist[2] == 3
        assert isinstance(result.autolist[1], Model)
        assert result.autolist[1].pk == pm.pk
        assert result.autolist[1].name == pm.name
        assert result.autolist[1].age == pm.age

        am.autodict = {"a": 1, "b": pm_dict}
        result = am.deserialize()
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"], Model)
        assert result.autodict["b"].pk == pm.pk
        assert result.autodict["b"].name == pm.name
        assert result.autodict["b"].age == pm.age

        am.autodict = {"a": 1, "b": [pm_dict]}
        result = am.deserialize()
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"][0], Model)
        assert result.autodict["b"][0].pk == pm.pk
        assert result.autodict["b"][0].name == pm.name
        assert result.autodict["b"][0].age == pm.age

        am.autodict = {"a": 1, "b": {"c": pm_dict}}
        result = am.deserialize()
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"]["c"], Model)
        assert result.autodict["b"]["c"].pk == pm.pk
        assert result.autodict["b"]["c"].name == pm.name
        assert result.autodict["b"]["c"].age == pm.age

    def test_automodel_serialize(self):
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
            assert testlist[i].pk == a["pk"]

        am.autodict = {a.pk: a for a in testlist}
        testdict = am.autodict.copy()
        result = am.serialize()
        # breakpoint()
        for k, a in result["autodict"].items():
            assert isinstance(a, dict)
            assert testdict[k].model_name() == a["_automodel"]
            assert testdict[k].pk == a["pk"]

    def test_automodel_circular_reference(self):
        am = Model(name="test", age=10, date=datetime.now())
        subam = Model(name="test", age=10, date=datetime.now())
        subam.auto = am
        am.auto = subam
        am.save()
        subam.save()

        am_ser = am.serialize()
        assert am_ser["auto"]["pk"] == subam.pk
        am.deserialize()
        assert am_ser["pk"] == am.pk
        assert am_ser["auto"].pk == subam.pk

        subam_ser = subam.serialize()
        assert subam_ser["auto"]["pk"] == am.pk
        subam.deserialize()
        assert subam_ser["pk"] == subam.pk
        assert subam_ser["auto"].pk == am.pk
