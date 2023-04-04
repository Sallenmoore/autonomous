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
    print("\n====file====\n")
    print(open(autonomous.__file__).read())

    print("\n====version====\n")
    version("autonomous")
    print(autonomous.__version__)
