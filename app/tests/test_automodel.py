from autolib import log
from autolib.autoencoder import AutoEncoder
from autolib.automodel import AutoModel


class TestAutomodel:
    def test_automodel_create(self):
        am = AutoModel()
        assert not am.pk
        assert am.table()
        am = AutoModel(name="test", age=10)
        assert am.name == "test"
        assert am.age == 10
        assert not am.pk

    def test_automodel_all_when_empty(self):
        results = AutoModel.all()
        log(results)

    def test_automodel_clear(self):
        AutoModel.clear_table()
        assert not AutoModel.all()

    def test_automodel_save(self):
        am = AutoModel(name="test", age=10)
        assert not am.pk
        am.save()
        log(am.pk)
        assert am.pk
        assert am.name == "test"
        assert am.age == 10

        AutoModel.clear_table()

    def test_automodel_get(self):
        am = AutoModel(name="test", age=10)
        assert not am.pk
        am.save()
        # breakpoint()
        new_am = AutoModel.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == am.name
        assert new_am.age == am.age

        new_am = AutoModel.get(None)
        assert not new_am
        new_am = AutoModel.get(-1)
        assert not new_am

        AutoModel.clear_table()

    def test_automodel_update(self):
        am = AutoModel(name="test", age=10)
        assert not am.pk
        am.save()
        assert am.pk
        assert am.name == "test"
        assert am.age == 10

        new_am = AutoModel.get(am.pk)
        new_am.name = "update"
        new_am.age = 99

        new_am.save()
        new_am = AutoModel.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == "update"
        assert new_am.age == 99

        AutoModel.clear_table()

    def test_automodel_delete(self):
        am = AutoModel(name="test", age=10)
        am.save()

        am.delete()

        new_am = AutoModel.get(am.pk)

        assert not new_am

        AutoModel.clear_table()

    # def test_automodel_serialize(self):
    #     am = AutoModel(name="test", age=10)
    #     am.save()
    #     assert 1 == am._serialize(1)
    #     assert 1.0 == am._serialize(1.0)
    #     assert "1" == am._serialize("1")

    #     result = am._serialize(am)
    #     assert isinstance(result, dict)
    #     assert result["automodel"] == am.__class__.__name__
    #     assert result["pk"] == am.pk

    #     assert am._serialize([1, 2, 3]) == [1, 2, 3]
    #     assert am._serialize({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    #     assert am._serialize([1, am, 3]) == [
    #         1,
    #         {"automodel": am.__class__.__name__, "pk": am.pk},
    #         3,
    #     ]
    #     assert am._serialize({"a": 1, "b": am}) == {
    #         "a": 1,
    #         "b": {"automodel": am.__class__.__name__, "pk": am.pk},
    #     }
    #     assert am._serialize({"a": 1, "b": [am]}) == {
    #         "a": 1,
    #         "b": [{"automodel": am.__class__.__name__, "pk": am.pk}],
    #     }
    #     assert am._serialize({"a": 1, "b": {"c": am}}) == {
    #         "a": 1,
    #         "b": {"c": {"automodel": am.__class__.__name__, "pk": am.pk}},
    #     }

    #     am.auto = AutoModel(name="subtest", age=11)
    #     data = am.serialize()
    #     assert data["name"] == "test"
    #     assert data["age"] == 10
    #     assert data["pk"] == am.pk
    #     assert data["auto"] == {
    #         "automodel": am.auto.__class__.__name__,
    #         "pk": am.auto.pk,
    #     }

    #     am.autolist = [AutoModel(name=f"sublisttest{i}", age=11) for i in range(3)]
    #     # breakpoint()
    #     data = am.serialize()
    #     for i, a in enumerate(data["autolist"]):
    #         assert a == {
    #             "automodel": AutoModel.__name__,
    #             "pk": am.autolist[i]["pk"],
    #         }

    #     am.autodict = {i: AutoModel(name=f"subdicttest{i}", age=11) for i in range(3)}
    #     data = am.serialize()
    #     for i, a in data["autodict"].items():
    #         assert a == {
    #             "automodel": AutoModel.__name__,
    #             "pk": am.autodict[i]["pk"],
    #         }

    #     AutoModel.clear_table()

    # def test_automodel_deserialize(self):

    #     assert 1 == AutoModel._deserialize(1)
    #     assert 1.0 == AutoModel._deserialize(1.0)
    #     assert "1" == AutoModel._deserialize("1")

    #     am_obj = AutoModel(name="test", age=10)
    #     am_obj.save()
    #     assert isinstance(AutoModel._deserialize(am_obj), AutoModel)

    #     am_dict = {"automodel": am_obj.__class__.__name__, "pk": am_obj.pk}

    #     result = AutoModel._deserialize(am_dict)
    #     assert isinstance(result, AutoModel)
    #     assert result.pk == am_obj.pk
    #     assert result.name == am_obj.name
    #     assert result.age == am_obj.age

    #     assert AutoModel._deserialize([1, 2, 3]) == [1, 2, 3]
    #     assert AutoModel._deserialize({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    #     result = AutoModel._deserialize([1, am_dict, 3])
    #     assert result[0] == 1
    #     assert result[2] == 3
    #     assert isinstance(result[1], AutoModel)
    #     assert result[1].pk == am_obj.pk
    #     assert result[1].name == am_obj.name
    #     assert result[1].age == am_obj.age

    #     result = AutoModel._deserialize({"a": 1, "b": am_dict})
    #     assert result["a"] == 1
    #     assert isinstance(result["b"], AutoModel)
    #     assert result["b"].pk == am_obj.pk
    #     assert result["b"].name == am_obj.name
    #     assert result["b"].age == am_obj.age

    #     result = AutoModel._deserialize({"a": 1, "b": [am_dict]})
    #     assert result["a"] == 1
    #     assert isinstance(result["b"][0], AutoModel)
    #     assert result["b"][0].pk == am_obj.pk
    #     assert result["b"][0].name == am_obj.name
    #     assert result["b"][0].age == am_obj.age

    #     result = AutoModel._deserialize({"a": 1, "b": {"c": am_dict}})
    #     assert result["a"] == 1
    #     assert isinstance(result["b"]["c"], AutoModel)
    #     assert result["b"]["c"].pk == am_obj.pk
    #     assert result["b"]["c"].name == am_obj.name
    #     assert result["b"]["c"].age == am_obj.age

    #     pk = AutoModel(name="subtest", age=11).save()
    #     am_dict["auto"] = {"automodel": AutoModel.__name__, "pk": pk}
    #     # breakpoint()
    #     am_reobj = AutoModel(**am_dict)
    #     assert isinstance(am_reobj, AutoModel)
    #     assert isinstance(am_reobj.auto, AutoModel)
    #     assert am_reobj.auto.name == "subtest"
    #     assert am_reobj.auto.pk == pk
    #     assert am_reobj.auto.age == 11

    #     subobjs = [AutoModel(name=f"subtest{i}", age=11) for i in range(3)]
    #     all(a.save() for a in subobjs)
    #     am_dict["autolist"] = [
    #         {"automodel": AutoModel.__name__, "pk": a.pk} for a in subobjs
    #     ]
    #     # breakpoint()
    #     am_reobj = AutoModel(**am_dict)
    #     for i, a in enumerate(am_reobj.autolist):
    #         assert isinstance(a, AutoModel)
    #         assert a.name == am_dict["autolist"][i].name
    #         assert a.pk == am_dict["autolist"][i].pk
    #         assert a.age == am_dict["autolist"][i].age

    #     am_dict["autodict"] = {
    #         i: {"automodel": AutoModel.__name__, "pk": a.pk}
    #         for i, a in enumerate(subobjs)
    #     }

    #     # breakpoint()
    #     am_reobj = AutoModel(**am_dict)
    #     for k, a in am_reobj.autodict.items():
    #         assert isinstance(a, AutoModel)
    #         assert a.name == am_dict["autodict"][k].name
    #         assert a.pk == am_dict["autodict"][k].pk
    #         assert a.age == am_dict["autodict"][k].age

    #     AutoModel.clear_table()
