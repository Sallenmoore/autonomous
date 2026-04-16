__version__ = "0.3.112"

from dotenv import load_dotenv

load_dotenv()

from .logger import get_logger, log


def init(**overrides) -> str:
    """Explicitly open the default MongoDB connection.

    Thin wrapper around ``autonomous.model.automodel.connect_from_env`` so
    consumers can write ``autonomous.init()`` at app startup. Keyword args
    (``host``, ``port``, ``username``, ``password``, ``db``) override the
    corresponding env vars. Idempotent.
    """
    from autonomous.model.automodel import connect_from_env

    return connect_from_env(**overrides)
