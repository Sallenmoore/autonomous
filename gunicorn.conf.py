import os

# Non logging stuff
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', 5000)}"
workers = 4
# Access log - records incoming HTTP requests
accesslog = "-"
# Error log - records Gunicorn server goings-on
errorlog = "-"
loglevel = "error"

## DEVELOPMENT OPTIONS
timeout = 120
workers = 2
# Whether to send output to the error log
capture_output = True
# How verbose the Gunicorn error logs should be
loglevel = "warning"

reload = True
reload_extra_files = ["templates/", "static/"]
