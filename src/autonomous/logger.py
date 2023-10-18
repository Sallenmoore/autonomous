import inspect
import logging
import os

from icecream import ic

# class LogFilter(logging.Filter):
#     def filter(self, record):
#         return record.levelno == LOG_LEVEL
log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class Logger:
    """
    Set the log level to by setting the LOG_LEVEL environment variable to:
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    Default: WARNING
    """

    def __init__(self):
        self.logger = logging.getLogger("gunicorn.error")
        level = os.environ.get("LOG_LEVEL") or self.logger.level
        self.logger.setLevel(log_levels.get(level, "DEBUG"))
        prefix = f"{os.environ.get('APP_NAME ', 'APP')}| "
        ic.configureOutput(prefix=prefix)
        self.enabled = True

    def set_level(self, level):
        self.logger.setLevel(log_levels[level])

    def enable(self, enable=True):
        self.enabled = enable

    def __call__(self, *args, **kwargs):
        if self.enabled:
            caller = inspect.stack()[1]
            fn = caller.filename.split("/")[-1]
            msg = f"\n\n{'='*20}\t{fn}:{caller.function}()::{caller.lineno}\t{'='*20}\n"
            msg += "\n========\n"
            if args:
                msg += ic.format(args)
            if kwargs:
                msg += ic.format(kwargs)
            self.logger.log(self.logger.level, f"{msg}\n")


log = Logger()
