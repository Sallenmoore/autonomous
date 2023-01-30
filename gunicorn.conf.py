import logging
import os

from gunicorn import glogging

# Non logging stuff
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', 5000)}"
workers = 4


# LOGGING


class CustomLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        self._set_handler(
            self.error_log,
            cfg.errorlog,
            logging.Formatter(
                fmt=(
                    "timestamp=%(asctime)s pid=%(process)d "
                    "loglevel=%(levelname)s msg=%(message)s"
                )
            ),
        )


accesslog = "-"
logger_class = CustomLogger
# Access log - records incoming HTTP requests
accesslog = "-"
# Error log - records Gunicorn server goings-on
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "INFO").upper()

## DEVELOPMENT OPTIONS
timeout = 120
workers = 2
# Whether to send output to the error log
capture_output = True
# How verbose the Gunicorn error logs should be

reload = True
reload_extra_files = ["templates/", "static/"]
