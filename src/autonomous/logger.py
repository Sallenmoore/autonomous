import inspect
import logging
import os

LOG_KEYS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}

def get_log_level():
    lvl = os.environ.get("LOG_LEVEL")
    if lvl:
        return LOG_KEYS.get(lvl, logging.INFO)
    else:
        return logging.INFO

LOG_LEVEL = get_log_level()

class LogFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s::%(levelname)s - %(message)s')
built_in_log = logging.getLogger(__name__)
built_in_log.addFilter(LogFilter())

class Logger:

    def __call__(self, *args, LEVEL=None):
        level = logging.getLevelName(LEVEL) if LEVEL else LOG_LEVEL
        caller = inspect.stack()[1]
        fn = caller.filename.split('/')[-1]
        msg = "\n\t".join([str(x) for x in args])
        built_in_log.log(level, f"\n{'='*40}\n{fn}:{caller.function}()[{caller.lineno}]\n\n\t{msg}\n")


# Global logger instance
log = Logger()