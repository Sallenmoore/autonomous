import inspect
import logging

LOG_LEVEL = logging.INFO

class LogFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format='%(levelname)s - %(message)s')
built_in_log = logging.getLogger(__name__)
built_in_log.addFilter(LogFilter())

class Logger:

    def __init__(LEVEL=LOG_LEVEL):
        LOG_LEVEL = LEVEL

    def __call__(self, *args, LEVEL=None):
        level = logging.getLevelName(LEVEL) if LEVEL else LOG_LEVEL
        caller = inspect.stack()[1]
        fn = caller.filename.split('/')[-1]
        msg = "\n".join([str(x) for x in args])
        built_in_log.log(level, f"[{fn}:{caller.function}():{caller.lineno}]\n\t{msg}\n")


# Global logger instance
log = Logger()