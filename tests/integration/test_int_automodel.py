from autonomous import log
from autonomous.model.autoattr import StringAttr
from autonomous.model.automodel import AutoModel


class RealModel(AutoModel):
    # set model default attributes
    name = StringAttr(default="")
    meta = {"allow_inheritance": True}


class ChildModel(RealModel):
    pass


class TestIntegratedAutomodel:
    def test_automodel_save(self):
        am = RealModel(name="test")
        am.save()
        assert am.model_name() == "RealModel"
        assert am.name == "test"

        # breakpoint()

        am = ChildModel(name="test")
        am.save()
        assert am.model_name() == "ChildModel"
        assert am.name == "test"
