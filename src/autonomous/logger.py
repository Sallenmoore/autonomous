import datetime
import inspect
import logging
import os

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
        self.enabled = True
        if not os.path.exists("logs"):
            os.makedirs("logs")
        self.logfile = "logs/current_run_error_log.log"
        self.logarchive = (
            f"logs/error_log-{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
        )

    def set_level(self, level):
        self.logger.setLevel(log_levels[level])

    def enable(self, enable=True):
        self.enabled = enable

    def __call__(self, *args, **kwargs):
        if self.enabled:
            is_printed = kwargs.pop("_print", False)
            caller = inspect.stack()[1]
            fn = caller.filename.split("/")[-1]
            msg = f"\n\n{'='*20}\t{fn}:{caller.function}()::{caller.lineno}\t{'='*20}\n"
            msg += f"\n{'='*20}\n"
            if args:
                msg += "\n---\n".join([f"{v}" for v in args])
            if kwargs:
                msg += "\n---\n".join([f"{k} : {v}" for k, v in kwargs.items()])
            msg += f"\n{'='*20}\n"
            self.logger.log(self.logger.level, f"{msg}\n")
            with open(self.logfile, "w") as current:
                current.write(f"{msg}\n")
            with open(self.logarchive, "a") as archive:
                archive.write(f"{msg}\n")
            if is_printed:
                print(msg)


log = Logger()
