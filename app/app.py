import os
import json 
import logging

from flask import Flask, request, render_template

class Config:
    APP_NAME = os.environ.get("APP_NAME", __name__)
    HOST=os.environ.get('HOST', '0.0.0.0')
    PORT=os.environ.get('PORT', 80)
    API_PORT=os.environ.get('API_PORT', '')
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "NATASHA")

class ProductionConfig(Config):
    DATABASE_URI = 'mysql://user@localhost/foo'
    LOG_LEVEL = logging.DEBUG
    DEBUG = False
    TESTING = False

class DevelopmentConfig(Config):
    DATABASE_URI = "sqlite:////tmp/foo.db"
    LOG_LEVEL =logging.ERROR
    DEBUG = True
    TESTING = True
    TRAP_HTTP_EXCEPTIONS=True

hello = HelloExtension()

def create_app():
    #################################################################
    #                             Extensions                        #
    #################################################################
    app = Flask(os.getenv("APP_NAME", __name__))
    app.config.from_object(DevelopmentConfig)
    
    #################################################################
    #                             Extensions                        #
    #################################################################

    hello.init_app(app)

    #################################################################
    #                             ROUTEs                            #
    #################################################################
    from views import (model)
    
    app.register_blueprint(model.bp)


    return app