
import os
import sys
import pprint

def DEBUG_PRINT(**kwargs):
    pp = pprint.PrettyPrinter(indent=4)
    objstr = "".join(f"[{k}:{v}]\n" for k, v in kwargs.items())
    pp.pprint(f"\t[DEBUG] {str(__file__)} - {sys._getframe(1).f_lineno}: {objstr}")



TESTING = os.environ.get("TESTING", False)
DEBUG = os.environ.get("DEBUG", False)
EXPLAIN_TEMPLATE_LOADING= os.environ.get("DEBUG", False)

FLASK_ENV = os.environ.get("ENV", 'production')
SECRET_KEY = os.environ.get("SECRET_KEY", None)
SCSS_ASSET_DIR= os.environ.get("STATIC_DIR", "static")
SCSS_STATIC_DIR=SCSS_ASSET_DIR

HOST=os.environ.get('HOST', '0.0.0.0')
PORT=os.environ.get('PORT', 80)