__version__ = "0.2.21"

from dotenv import load_dotenv

load_dotenv()

from .logger import log
from .model.automodel import AutoModel
