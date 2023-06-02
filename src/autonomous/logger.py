import inspect
import logging
import os
import pprint

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
        self.logger.setLevel(log_levels[level])

    def set_level(self, level):
        self.logger.setLevel(log_levels[level])

    def __call__(self, *args, **kwargs):
        caller = inspect.stack()[1]
        fn = caller.filename.split("/")[-1]
        msg = f"\n{'='*40}\n{fn}:{caller.function}()::{caller.lineno}\n\n"
        if kwargs:
            args = list(args)
            args += [{k: v} for k, v in kwargs.items()]
        msg += "\n\n=====\n\n".join([pprint.pformat(a, indent=4) for a in args])
        self.logger.log(self.logger.level, f"{msg}\n")


log = Logger()
