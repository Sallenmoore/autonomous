#local modules
from selflib.logger import log
from selflib.utilities import package_response, unpackage_response
from models.modeltest import ModelTest
#external Modules
import pytest
from flask import Flask, request

# Built-In Modules
import os
from pathlib import Path
import shutil

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('config.Config') 

    #TODO: ensure the instance folder exists ???is this necessary?
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    with app.app_context():

        @app.route('/', methods=('GET',))
        def modeltest():
            return {"working":"it is"}
        
        @app.route('/modeltest/<int:pk>', methods=('GET',))
        def modeltestget(pk):
            mt = ModelTest.get(pk)
            log(f"modeltestget: {mt}")
            return package_response(data=mt)

        @app.route('/modeltest/all', methods=('GET',))
        def modeltestall():
            mt = ModelTest.all()
            return package_response(data=mt)

        @app.route('/modeltest/search/', methods=('GET',))
        def modeltestsearch():
            mt = ModelTest.search(**request.values)
            return package_response(data=mt)

        @app.route('/modeltest/create', methods=('POST',))
        @app.route('/modeltest/update', methods=('POST',))
        def modeltestupdate():
            kwargs = unpackage_response(request.json)
            log(f"kwargs: {kwargs}")
            ch = ModelTest(**kwargs)
            log(f"ch: {vars(ch)}")
            pk = ch.save()
            if not pk:
                return package_response(error="Test could not be saved. Unknown error.")
            return package_response(data=ch)

        @app.route('/modeltest/delete', methods=('POST',))
        def modeltestdelete():
            pk = unpackage_response(request.json)
            mt = ModelTest.get(pk)
            mt.delete()
            return package_response(data=mt)

        return app

#application factory
app = create_app()
