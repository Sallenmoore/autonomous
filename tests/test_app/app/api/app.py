from autonomous import log
from autonomous import config, response
#from autonomous import create_app
from models.modeltest import ModelTest
from models.submodeltest import SubModelTest

# External Modules
from flask import Flask, request

# Built-In Modules
import os

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config)

    #TODO: ensure the instance folder exists ???is this necessary?
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    with app.app_context():

        ModelTest.crud(app)
        SubModelTest.crud(app)

        @app.get('/')
        def index():
            return {"working": "it is"}
        
        return app
#application factory
app = create_app()