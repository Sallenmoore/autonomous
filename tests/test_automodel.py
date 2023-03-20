from datetime import datetime
from typing import Optional

from src.autonomous import log
from src.autonomous.autodb import Database
from src.autonomous.automodel import AutoModel


class Model(AutoModel):
    # set model default attributes
    name: str
    age: int
    date: datetime
    auto: Optional["Model"]
    autolist: Optional[list]
    autodict: Optional[dict]
    autoobj: Optional["Model"]


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

        Database.cleardb()

    def test_automodel_get(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()

        new_am = Model.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == am.name
        assert new_am.age == am.age

        new_am = Model.get(None)
        assert not new_am
        new_am = Model.get(-1)
        assert not new_am

        Database.cleardb()

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

        Database.cleardb()

    def test_automodel_delete(self):
        am = Model(name="test", age=10, date=datetime.now())
        am.save()

        am.delete()
        new_am = Model.get(am.pk)

        assert not new_am

        Database.cleardb()

    def test_automodel_deserialize(self):

        am = Model(name="test", age=10, date=datetime.now())
        am.save()
        am_dict = {"_automodel": am.__class__.__name__, "_pk": am.pk}
        result = Model._deserialize(am_dict)
        assert isinstance(result, Model)
        assert result.pk == am.pk
        assert result.name == am.name
        assert result.age == am.age

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

        Database.cleardb()

    def test_autoencoder_serialize(self):
        am = Model(name="test", age=11)
        am.save()

        subobjs = [Model(name=f"subtest{i}", age=11).save() for i in range(3)]
        am.autolist = subobjs

        # breakpoint()
        Model.serialize(am)
        for i, a in enumerate(am.autolist):
            assert isinstance(a, Model)
            assert a.name == am.autolist[i].name
            assert a.pk == am.autolist[i].pk
            assert a.age == am.autolist[i].age

        am.autodict = {
            i: {"_automodel": Model.__name__, "_pk": a.pk}
            for i, a in enumerate(subobjs)
        }

        # breakpoint()
        Model.serialize(am)
        # breakpoint()
        for k, a in am.autodict.items():
            assert isinstance(a, Model)
            assert a.name == am.autodict[k].name
            assert a.pk == am.autodict[k].pk
            assert a.age == am.autodict[k].age

        Database.cleardb()
