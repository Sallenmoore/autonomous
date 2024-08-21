import random
import uuid
from datetime import datetime
from typing import Optional

import bson
import pytest
from autonomous import log
from autonomous.model.automodel import AutoModel


class MockORM:
    def __init__(self, name, attributes):
        log(attributes)
        self.name = name
        self.table = {}

    def save(self, data):
        if data.get("pk") is None:
            data["pk"] = str(bson.ObjectId())
        self.table[data["pk"]] = data
        log(data)
        return data["pk"]

    def get(self, pk):
        # log(pk, self.db.get(pk))
        return self.table.get(pk)

    def random(self):
        key = random.choice(list(self.table.keys()))
        return self.table[key]

    def all(self):
        # log(self.db.values())
        return self.table.values()

    def search(self, **kwargs):
        results = []
        for key, value in kwargs.items():
            for item in self.table.values():
                if item[key] == value:
                    results.append(item)
        results = list(set(results))
        # log(results)
        return results

    def delete(self, pk):
        try:
            del self.table[pk]
        except KeyError:
            return pk
        else:
            return None


class SubModel(AutoModel):
    # set model default attributes
    name: str = ""
    age: int = None
    date: datetime = None


class Model(AutoModel):
    # set model default attributes
    name: str = ""
    age: int = None
    date: datetime = None
    auto: Optional["Model"] = None
    autolist: list = []
    autodict: dict = {}
    autoobj: Optional["Model"] = None


# @pytest.mark.skip(reason="dumb test")
class TestAutomodel:
    def test_automodel_create(self):
        am = Model(name="test", age=10, date=datetime.now())
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()
        # assert am.pk

    def test_automodel_all_when_empty(self):
        Model.table().flush_table()
        results = Model.all()
        log(results)

    def test_automodel_save(self):
        am = Model(name="test", age=10, date=datetime.now())
        # breakpoint()
        pk = am.save()
        assert pk
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

    def test_automodel_random(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        new_am = Model.random()
        assert new_am.pk
        assert new_am.name
        assert new_am.age

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

        result = Model(pk=am.pk)

        assert isinstance(result, Model)
        assert result.pk == am.pk
        assert result.name == am.name
        assert result.age == am.age
        assert result.date == am.date

        pm_dict = {
            "automodel_": pm.model_name(qualified=True),
            "pk": pm.pk,
        }
        # log("Autolist", pm.autolist)
        pm.autolist = [1, pm_dict, 3]
        # log("Autolist", pm.autolist)
        assert pm.autolist[0] == 1
        assert pm.autolist[2] == 3
        assert isinstance(pm.autolist[1], Model)

        assert pm.autolist[1].pk == pm.pk
        assert pm.autolist[1].name == pm.name
        assert pm.autolist[1].age == pm.age

        result = Model(autodict={"a": 1, "b": pm_dict})
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"], Model)
        assert result.autodict["b"].pk == pm.pk
        assert result.autodict["b"].name == pm.name
        assert result.autodict["b"].age == pm.age

        result = Model(autodict={"a": 1, "b": [pm_dict]})
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"][0], Model)
        assert result.autodict["b"][0].pk == pm.pk
        assert result.autodict["b"][0].name == pm.name
        assert result.autodict["b"][0].age == pm.age

        result = Model(autodict={"a": 1, "b": {"c": pm_dict}})
        assert result.autodict["a"] == 1
        assert isinstance(result.autodict["b"]["c"], Model)
        assert result.autodict["b"]["c"].pk == pm.pk
        assert result.autodict["b"]["c"].name == pm.name
        assert result.autodict["b"]["c"].age == pm.age

    def test_automodel_circular_reference(self):
        am = Model(name="testam", age=10, date=datetime.now())
        am.save()
        subam = Model(name="testsub", age=10, date=datetime.now())
        subam.save()
        subam.auto = am
        am.auto = subam

        assert am.auto == subam
        assert subam.auto == am

        am.auto = am
        am.save()
        assert am.auto == am
        assert am.auto.name == "testam"
        am.auto.name = "updated"
        am.auto.save()
        assert am.auto.name == "updated"
        assert am.name == "updated"

    def test_automodel_dangling_reference(self):
        am = Model(name="testam", age=10, date=datetime.now())
        am.save()
        subam = Model(name="testsub", age=10, date=datetime.now())
        subam.save()
        am.auto = subam
        am.autolist.insert(0, subam)
        am.save()
        subam.delete()
        am = Model.get(am.pk)
        with pytest.raises(AttributeError):
            breakpoint()
            assert not am.auto.pk
        with pytest.raises(IndexError):
            assert not am.autolist[0].pk
        assert am.autolist == []
