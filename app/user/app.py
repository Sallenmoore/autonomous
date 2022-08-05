# Required Imports
import os
import sass
import requests
import json
from flask import Flask, render_template, request, redirect, url_for, session

import logging
logging.basicConfig(level=logging.INFO, format="==%(levelname)s== [%(filename)s - %(funcName)s:%(lineno)d] --\n %(message)s")
log = logging.getLogger()

def create_app(test_config=None):
    app = Flask(__name__)

    #set to 'config.Config' to use ENV_VARS
    #set to 'config.DevConfig' to use development settings
    #set to 'config.ProdConfig' to use production settings
    app.config.from_object('config.DevConfig') 
    
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # TODO - Find a better way to compile sass during development
    if os.environ.get("ENV") == 'development':
        @app.before_request
        def before_request_tasks():
            sass.compile(dirname=('./static/style/sass', './static/style'), output_style='nested')

    with app.app_context():

        ################################################################
        ####                       Base Routes                       ###
        ################################################################
        
        # Include our Routes
        @app.route('/', methods=('GET', 'POST'))
        def index():
            context = {
                'msg': "Hello World!", 
            }
            return render_template("index.html", **context)

        ################################################################
        ###                       Additional Routes                  ###
        ################################################################
        
        # Replace views with a list of blueprint views
        # and register each view
        
        # from src.views import (views, ...)
        # app.register_blueprint(view.bp)
        # app.register...

        # You MUST register filters to use them in templates
        from src.filters import filters
        app.jinja_env.filters['filter name'] = filters.markdown_to_html

    ###### returns the application instance to the caller ######

    return app