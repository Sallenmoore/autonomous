import inspect
import logging
import pprint

# class LogFilter(logging.Filter):
#     def filter(self, record):
#         return record.levelno == LOG_LEVEL


class Logger:
    def __init__(self):
        self.logger = logging.getLogger("gunicorn.error")
        # built_in_log.addFilter(LogFilter())

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
