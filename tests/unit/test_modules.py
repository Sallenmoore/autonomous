import sys
import pytest


# @pytest.mark.skip(reason="dumb")
def test_imports():
    for p in sys.path:
        print(p)
    """Test that all modules can be imported."""
    for module in (
        "autonomous.apis",
        "autonomous.assets",
        "autonomous.model.automodel",
        "autonomous.logger",
    ):
        __import__(module)


def test_log():
    from autonomous import log

    log(1, "hello")
