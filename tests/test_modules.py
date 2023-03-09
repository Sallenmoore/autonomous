import sys


def test_imports():

    for p in sys.path:
        print(p)
    """Test that all modules can be imported."""
    for module in (
        "src.autonomous.apis",
        "src.autonomous.version_control",
        "src.autonomous.assets",
        "src.autonomous.automodel",
        "src.autonomous.logger",
    ):
        __import__(module)
