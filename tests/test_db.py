from datetime import datetime
from typing import Optional

import redis_om

from src.autonomous.autodb import Database


class Model(redis_om.JsonModel):
    # set model default attributes
    name: str
    age: int
    autolist: Optional[list]
    autodict: Optional[dict]


class TestAutoDB:
    def test_db_start(self):
        Database.cleardb()

    def test_db_create(self):
        am = Model(name="test", age=10)
        assert am.name == "test"
        assert am.age == 10
        am.save()

        # TODO: add submodels tests
        am.autolist = [1, 2, 3]
        am.autodict = {"a": 1, "b": 2, "c": 3}
        am.save()

        assert am.autolist == [1, 2, 3]
        assert am.autodict == {"a": 1, "b": 2, "c": 3}

        TestAutoDB.test_db_start(self)

    def test_db_read(self):
        am = Model(name="test", age=10)
        am.save()
        result = Model.get(am.pk)
        assert result.name == am.name
        assert result.age == am.age
        assert result.pk == am.pk

        # TODO: add submodels tests
        am.autolist = [1, 2, 3]
        am.autodict = {"a": 1, "b": 2, "c": 3}
        am.save()

        result = Model.get(am.pk)
        assert result.autolist == [1, 2, 3]
        assert result.autodict == {"a": 1, "b": 2, "c": 3}

        TestAutoDB.test_db_start(self)

    def test_db_update(self):
        am = Model(name="test", age=10)
        am.save()
        am.name = "test2"
        am.save()
        result = Model.get(am.pk)
        assert result.name == am.name
        assert result.age == am.age
        assert result.pk == am.pk

        # TODO: add submodels tests
        am.autolist = [1, 2, 3]
        am.autodict = {"a": 1, "b": 2, "c": 3}
        am.save()

        am.autolist = [11, 21, 31]
        am.autodict = {"x": 11, "y": 21, "z": 31}
        am.save()

        result = Model.get(am.pk)
        assert result.autolist == [11, 21, 31]
        assert result.autodict == {"x": 11, "y": 21, "z": 31}

        TestAutoDB.test_db_start(self)

    def test_db_delete(self):
        am = Model(name="test", age=10)
        am.save()
        am.delete(am.pk)
        try:
            Model.get(am.pk)
        except redis_om.model.model.NotFoundError as e:
            pass
        else:
            assert False

        TestAutoDB.test_db_start(self)
