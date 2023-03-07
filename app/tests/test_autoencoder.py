import json
from datetime import datetime

from autonomous import log
from autonomous.autoencoder import AutoEncoder
from models.model import Model


class TestAutoencoder:
    def test_autoencoder_serialize(self):

        assert 1 == AutoEncoder._serialize(1)
        assert 1.0 == AutoEncoder._serialize(1.0)
        assert "1" == AutoEncoder._serialize("1")

        # Test datetime objects
        dt_serialized = AutoEncoder._serialize(datetime.now())
        assert isinstance(dt_serialized, str)
        assert datetime.fromisoformat(dt_serialized)

        # Test serializing Model
        am = Model(name="test", age=10)
        am.save()
        result = AutoEncoder._serialize(am)
        assert isinstance(result, dict)
        assert result["_automodel"] == am.__class__.__name__
        assert result["_pk"] == am.pk

        assert AutoEncoder._serialize([1, 2, 3]) == [1, 2, 3]
        assert AutoEncoder._serialize({"a": 1, "b": 2}) == {"a": 1, "b": 2}

        assert AutoEncoder._serialize([1, am, 3]) == [
            1,
            {"_automodel": am.__class__.__name__, "_pk": am.pk},
            3,
        ]
        assert AutoEncoder._serialize({"a": 1, "b": am}) == {
            "a": 1,
            "b": {"_automodel": am.__class__.__name__, "_pk": am.pk},
        }
        assert AutoEncoder._serialize({"a": 1, "b": [am]}) == {
            "a": 1,
            "b": [{"_automodel": am.__class__.__name__, "_pk": am.pk}],
        }
        assert AutoEncoder._serialize({"a": 1, "b": {"c": am}}) == {
            "a": 1,
            "b": {"c": {"_automodel": am.__class__.__name__, "_pk": am.pk}},
        }

    def test_autoencoder_default(self):
        am = Model(name="test", age=10)
        data = AutoEncoder().default(am)
        assert data["name"] == "test"
        assert data["age"] == 10

        am.auto = Model(name="subtest", age=11)
        data = AutoEncoder().default(am)
        assert data["auto"] == {
            "_automodel": am.auto.__class__.__name__,
            "_pk": am.auto.pk,
        }

        am.autolist = [Model(name=f"sublisttest{i}", age=11) for i in range(3)]
        # breakpoint()
        data = AutoEncoder().default(am)
        for i, a in enumerate(data["autolist"]):
            assert a == {
                "_automodel": Model.__name__,
                "_pk": am.autolist[i]["_pk"],
            }

        am.autodict = {i: Model(name=f"subdicttest{i}", age=11) for i in range(3)}
        data = AutoEncoder().default(am)
        for i, a in data["autodict"].items():
            assert a == {
                "_automodel": Model.__name__,
                "_pk": am.autodict[i]["_pk"],
            }

        Model.clear_table()

    def test_autoencoder__decode(self):
        assert 1 == AutoEncoder._decode(1)
        assert 1.0 == AutoEncoder._decode(1.0)
        assert "1" == AutoEncoder._decode("1")

        am_obj = Model(name="test", age=10)
        # breakpoint()
        am_obj.save()
        # breakpoint()
        am_dict = {"_automodel": am_obj.__class__.__name__, "_pk": am_obj.pk}
        result = AutoEncoder._decode(am_dict)
        assert isinstance(result, Model)
        assert result.pk == am_obj.pk
        assert result.name == am_obj.name
        assert result.age == am_obj.age

        assert AutoEncoder._decode([1, 2, 3]) == [1, 2, 3]
        assert AutoEncoder._decode({"a": 1, "b": 2}) == {"a": 1, "b": 2}

        result = AutoEncoder._decode([1, am_dict, 3])
        assert result[0] == 1
        assert result[2] == 3
        assert isinstance(result[1], Model)
        assert result[1].pk == am_obj.pk
        assert result[1].name == am_obj.name
        assert result[1].age == am_obj.age

        result = AutoEncoder._decode({"a": 1, "b": am_dict})
        assert result["a"] == 1
        assert isinstance(result["b"], Model)
        assert result["b"].pk == am_obj.pk
        assert result["b"].name == am_obj.name
        assert result["b"].age == am_obj.age

        result = AutoEncoder._decode({"a": 1, "b": [am_dict]})
        assert result["a"] == 1
        assert isinstance(result["b"][0], Model)
        assert result["b"][0].pk == am_obj.pk
        assert result["b"][0].name == am_obj.name
        assert result["b"][0].age == am_obj.age

        result = AutoEncoder._decode({"a": 1, "b": {"c": am_dict}})
        assert result["a"] == 1
        assert isinstance(result["b"]["c"], Model)
        assert result["b"]["c"].pk == am_obj.pk
        assert result["b"]["c"].name == am_obj.name
        assert result["b"]["c"].age == am_obj.age

    def test_autoencoder_decode(self):
        am = Model(name="test", age=11)
        pk = am.save()
        am_decoded = AutoEncoder.decode(am.__dict__)
        assert isinstance(am_decoded, dict)
        assert am_decoded["name"] == "test"
        assert am_decoded["age"] == 11
        assert am_decoded["_pk"] == pk

        subobjs = [Model(name=f"subtest{i}", age=11) for i in range(3)]
        all(a.save() for a in subobjs)
        am_decoded["autolist"] = [
            {"_automodel": Model.__name__, "_pk": a.pk} for a in subobjs
        ]
        # breakpoint()
        am_reobj = AutoEncoder.decode(am_decoded)
        for i, a in enumerate(am_reobj["autolist"]):
            assert isinstance(a, Model)
            assert a.name == am_decoded["autolist"][i].name
            assert a.pk == am_decoded["autolist"][i].pk
            assert a.age == am_decoded["autolist"][i].age

        am_decoded["autodict"] = {
            i: {"_automodel": Model.__name__, "_pk": a.pk}
            for i, a in enumerate(subobjs)
        }

        # breakpoint()
        am_reobj = AutoEncoder.decode(am_decoded)
        # breakpoint()
        for k, a in am_reobj["autodict"].items():
            assert isinstance(a, Model)
            assert a.name == am_decoded["autodict"][k].name
            assert a.pk == am_decoded["autodict"][k].pk
            assert a.age == am_decoded["autodict"][k].age

        Model.clear_table()
