import sys
from os.path import dirname, abspath, join

root_dir = f"{dirname(dirname(abspath(__file__)))}/src"

sys.path.append(root_dir)

root_dir = f"{dirname(dirname(abspath(__file__)))}/test_app"

sys.path.append(root_dir)