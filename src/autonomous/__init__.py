from .logger import log

# External Modules
from flask import Flask, request

# Built-In Modules
import os, sys, shutil, logging, inspect
from pathlib import Path

class Config:
    APP_NAME = os.environ.get("APP_NAME", "app")
    
    DEBUG = os.environ.get("DEBUG", False)
    TESTING = DEBUG
    FLASK_ENV = 'development' if DEBUG else 'production'
    FLASK_DEBUG = DEBUG
    FLASK_SECRET_KEY = os.environ.get("NATASHA")
    SECRET_KEY = os.environ.get("SECRET_KEY", "secretkey")
    
    HOST=os.environ.get('HOST', '0.0.0.0')
    PORT=os.environ.get('PORT', 7357)
    API_PORT=os.environ.get('API_PORT', 7357)
    
    LOG_LEVEL = os.environ.get("LOG_LEVEL", logging.INFO)
    

def create_app():
    frame = inspect.stack()[1][0].f_code.co_filename
    path = os.path.realpath(frame)

    app = Flask(
        os.getenv("APP_NAME", __name__),
        root_path=path,
    )
    app.config.from_object(Config()) 

    #TODO: ensure the instance folder exists ???is this necessary?
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    return app