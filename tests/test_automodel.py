from datetime import datetime

from app_template.app.models.model import Model
from autonomous import log


class TestAutomodel:
    def test_automodel_create(self):
        am = Model()
        assert not am.pk
        assert am.table()
        am = Model(name="test", age=10)
        assert am.name == "test"
        assert am.age == 10
        assert not am.pk

    def test_automodel_all_when_empty(self):
        results = Model.all()
        log(results)

    def test_automodel_clear(self):
        Model.clear_table()
        assert not Model.all()

    def test_automodel_save(self):
        am = Model(name="test", age=10)
        assert not am.pk
        am.save()
        log(am.pk)
        assert am.pk
        assert am.name == "test"
        assert am.age == 10

        Model.clear_table()

    def test_automodel_get(self):
        am = Model(name="test", age=10)
        assert not am.pk
        am.save()
        # breakpoint()
        new_am = Model.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == am.name
        assert new_am.age == am.age

        new_am = Model.get(None)
        assert not new_am
        new_am = Model.get(-1)
        assert not new_am

        Model.clear_table()

    def test_automodel_update(self):
        am = Model(name="test", age=10)
        assert not am.pk
        am.save()
        assert am.pk
        assert am.name == "test"
        assert am.age == 10

        new_am = Model.get(am.pk)
        new_am.name = "update"
        new_am.age = 99

        new_am.save()
        new_am = Model.get(am.pk)
        assert new_am.pk == am.pk
        assert new_am.name == "update"
        assert new_am.age == 99

        Model.clear_table()

    def test_automodel_delete(self):
        am = Model(name="test", age=10)
        am.save()

        am.delete()

        new_am = Model.get(am.pk)

        assert not new_am

        Model.clear_table()
