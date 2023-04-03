import inspect
import sys
from importlib.metadata import version

import autonomous


def test_imports():

    submodules = inspect.getmembers(autonomous)
    print("\n====members====\n")
    for name, module in submodules:
        if "builtins" not in name:
            print(name, module)
    # print("\n====sys.path====\n")
    # for p in sys.path:
    #     print(p)

    print("\n====versions====\n")
    print(open("/var/tmp/requirements.txt.log").read())

    print("\n====init====\n")
    print(open(autonomous.__file__).read())

    print("\n====version====\n")
    version("autonomous")
    print(autonomous.__version__)
    """Test that all modules can be imported."""
    for module in (
        "autonomous.apis",
        "autonomous.version_control",
        "autonomous.assets",
        "autonomous.automodel",
        "autonomous.autodb",
        "autonomous.logger",
    ):
        __import__(module)
