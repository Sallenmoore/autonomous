from .utilities import APP_NAME
import inspect
import logging

LOG_LEVEL = logging.INFO

class LogFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s - %(message)s')
built_in_log = logging.getLogger(APP_NAME)
built_in_log.addFilter(LogFilter())

class Logger:

    def __init__(LEVEL=LOG_LEVEL):
        LOG_LEVEL = LEVEL

    def __call__(self, msg, LEVEL=None):
        level = logging.getLevelName(LEVEL) if LEVEL else LOG_LEVEL
        caller = inspect.stack()[1]
        fn = caller.filename.removeprefix("/var/app/")
        built_in_log.log(level, f"[{fn}:{caller.function}():{caller.lineno}] {msg}")


# Global logger instance
log = Logger()