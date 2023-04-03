import sys

from app.models.model import Model

from autonomous import log


class TestApp:
    def test_model(self):
        for p in sys.path:
            print(p)

        m = Model(name="test")
