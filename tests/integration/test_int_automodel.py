import uuid
from datetime import datetime

from autonomous import log
from autonomous.model.automodel import AutoModel


class RealModel(AutoModel):
    # set model default attributes
    attributes = {
        "name": "",
    }


class ChildModel(RealModel):
    pass


class TestAutomodel:
    def test_automodel_save(self):
        am = RealModel(name="test")
        am.save()
        assert am.table().table.name == "RealModel"
        assert am.name == "test"

        # breakpoint()

        am = ChildModel(name="test")
        am.save()
        assert am.table().name == "ChildModel"
        assert am.table().table.name == "ChildModel"
        assert am.name == "test"
