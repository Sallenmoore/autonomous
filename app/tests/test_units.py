from utils import log
from utils.automodel import AutoModel


class TestApp:
    def test_automodel_create(self):
        am = AutoModel()
        assert not am.pk
        assert am._table
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
