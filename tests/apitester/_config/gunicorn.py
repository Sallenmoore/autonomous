import os
# Non logging stuff
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', 7537)}"
workers = 3
# Error log - records Gunicorn server goings-on
errorlog = "-"
syslog = True
# Whether to send output to the error log 
capture_output = True
# How verbose the Gunicorn error logs should be 
loglevel = "info"
# logconfig_dict = {
#     'disable_existing_loggers': False,
#     'formatters': { 
#         'default': { 'format': '%(asctime)s: %(message)s'},
#     }
# }

reload=True

## DEBUG Options

#spew=True #Install a trace function that spews every line executed by the server.

# Access log - records incoming HTTP requests
accesslog = "-"