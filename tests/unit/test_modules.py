import sys


def test_imports():

    for p in sys.path:
        print(p)
    """Test that all modules can be imported."""
    for module in (
        "autonomous.apis",
        "autonomous.version_control",
        "autonomous.assets",
        "autonomous.automodel",
        "autonomous.db.autodb",
        "autonomous.logger",
    ):
        __import__(module)