__version__ = "0.1.47"

from .logger import log
from .model.automodel import AutoModel
from .auth.autoauth import AutoAuth

current_user = AutoAuth.current_user
