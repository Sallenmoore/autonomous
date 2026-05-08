from datetime import datetime

import pytest

from autonomous import log
from autonomous.model.autoattr import (
    DateTimeAttr,
    IntAttr,
    ListAttr,
    ReferenceAttr,
    StringAttr,
)
from autonomous.model.automodel import AutoModel


class SubModel(AutoModel):
    # set model default attributes
    name = StringAttr(default="")
    age = IntAttr()
    date = DateTimeAttr()


class Model(AutoModel):
    # set model default attributes
    name = StringAttr(default="")
    age = IntAttr()
    date = DateTimeAttr()
    auto = ReferenceAttr()
    autolist = ListAttr(ReferenceAttr())


class AbstractModel(AutoModel):
    meta = {"abstract": True}
    # set model default attributes
    name = StringAttr(default="")
    age = IntAttr()
    auto = ReferenceAttr()


class AbstractModel2(AbstractModel):
    meta = {"abstract": True}
    # set model default attributes
    date = DateTimeAttr()


class RealModel(AbstractModel2):
    # set model default attributes
    name = StringAttr(default="")
    age = IntAttr()
    auto = ReferenceAttr()


class TestAutomodel:
    def test_automodel_create(self):
        am = Model(name="test", age=10, date=datetime.now())
        assert am.name == "test"
        assert am.age == 10
        assert am.date <= datetime.now()
        # assert am.pk

    def test_automodel_all_when_empty(self):
        Model.drop_collection()
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
        # breakpoint()
        result = Model(pk=am.pk, date=am.date)
        assert isinstance(result, Model)
        assert result.pk == am.pk
        assert result.name == am.name
        assert result.age == am.age
        assert result.date <= am.date

        # log("Autolist", pm.autolist)
        pm.autolist = [pm, am]
        assert isinstance(pm.autolist[0], Model)
        assert isinstance(pm.autolist[1], Model)

        assert pm.autolist[0].pk == pm.pk
        assert pm.autolist[0].name == pm.name
        assert pm.autolist[0].age == pm.age

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
        subam2 = Model(name="testsub2", age=10, date=datetime.now())
        subam2.save()
        am.auto = subam
        am.autolist.append(subam)
        am.autolist.append(subam2)
        am.save()
        subam.delete()
        am = Model.get(am.pk)
        assert am.auto is None
        assert len(am.autolist) == 1

    def test_referenceattr_update_persists_after_save(self):
        """Regression: ReferenceAttr assignment on an already-saved doc must
        mark the field dirty so the next save() includes it in $set.

        Steps:
          1. Create and save two independent Model instances (am, sub1).
          2. Assign am.auto = sub1 and save → persists reference.
          3. Create a third instance (sub2), save it.
          4. Re-fetch am from DB (clean state, _changed_fields=[]).
          5. Assign am.auto = sub2 — this is the regression scenario.
          6. Assert 'auto' in am._changed_fields immediately after assignment.
          7. Save am.
          8. Re-fetch am from DB and assert am.auto.pk == sub2.pk.
        """
        am = Model(name="testam", age=10, date=datetime.now())
        am.save()
        sub1 = Model(name="sub1", age=1, date=datetime.now())
        sub1.save()
        sub2 = Model(name="sub2", age=2, date=datetime.now())
        sub2.save()

        # Prime: set auto → sub1 and persist
        am.auto = sub1
        am.save()

        # Clean re-fetch (simulates the real-world scenario)
        am = Model.get(am.pk)
        assert am.auto.pk == sub1.pk

        # Regression: assign a *different* reference on the already-saved doc
        am.auto = sub2
        assert "auto" in am._changed_fields, (
            "_changed_fields must contain 'auto' immediately after assignment"
        )

        am.save()

        # Re-fetch and verify the new value was persisted
        am_reloaded = Model.get(am.pk)
        assert am_reloaded.auto is not None, "auto field must not be None after save"
        assert am_reloaded.auto.pk == sub2.pk, (
            f"Expected auto.pk={sub2.pk} but got {am_reloaded.auto.pk!r}"
        )

    def test_abstractmodel_all(self):
        RealModel.drop_collection()
        RealModel(name="test", age=10).save()
        results = RealModel.all()
        log([r._data for r in results])
        assert results
