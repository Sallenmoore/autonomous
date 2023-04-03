import os
from glob import glob

# Non logging stuff
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', 5000)}"
workers = 4


# LOGIN
accesslog = "-"
access_log_format = "%(U)s -  %(m)s - response time: %(M)s %(b)s \n"
# Access log - records incoming HTTP requests
accesslog = "-"
# Error log - records Gunicorn server goings-on
errorlog = "-"
error_log_format = "%(U)s -  %(m)s - response time: %(M)s %(b)s \n"
loglevel = os.environ.get("LOG_LEVEL", "INFO").upper()

## DEVELOPMENT OPTIONS
timeout = 120
workers = 2
# Whether to send output to the error log
capture_output = False
# How verbose the Gunicorn error logs should be

reload = True

reload_extra_files = ["templates/"] + glob("static/**/*", recursive=True)
