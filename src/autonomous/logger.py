import inspect
import logging
import os
import pprint

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
    
    def __call__(self, *args, LEVEL=None, **kwargs):
        level = logging.getLevelName(LEVEL) if LEVEL else LOG_LEVEL
        caller = inspect.stack()[1]
        fn = caller.filename.split('/')[-1]
        msg = f"\n{'='*40}\n{fn}:{caller.function}()::{caller.lineno}\n\n"

        params = list(args)
        if kwargs:
            params+= [{k:v} for k,v in kwargs.items()]
            
        msg += "\n\n=====\n\n".join([pprint.pformat(a, indent=2, compact=False) for a in params])
        built_in_log.log(level, f"{msg}\n")
