import os
import sys
from pathlib import Path

from dotenv import load_dotenv

dotenv_path = Path("tests/.testenv")
load_dotenv(dotenv_path=dotenv_path)
# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
