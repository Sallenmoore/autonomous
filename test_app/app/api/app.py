from autonomous.logger import log
from autonomous import config, response
#from autonomous import create_app
from models.modeltest import ModelTest

# External Modules
from flask import Flask, request

# Built-In Modules
import os

def create_app():
    app = Flask(os.getenv("APP_NAME", __name__))
    app.config.from_object(config)

    #TODO: ensure the instance folder exists ???is this necessary?
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    with app.app_context():

        @app.route('/modeltest/<int:pk>', methods=('GET',))
        def modeltestget(pk):
            mt = ModelTest.get(pk)
            #log(f"modeltestget: {mt}")
            return response.Response.package(data=mt)

        @app.route('/modeltest/all', methods=('GET',))
        def modeltestall():
            mt = ModelTest.all()
            return response.Response.package(data=mt)

        @app.route('/modeltest/search/', methods=('GET',))
        def modeltestsearch():
            mt = ModelTest.search(**request.values)
            return response.Response.package(data=mt)

        @app.route('/modeltest/create', methods=('POST',))
        def modeltestcreate():
            kwargs = response.Response.unpackage(request.json)
            #log(f"kwargs: {kwargs}")
            ch = ModelTest(**kwargs)
            #log(f"ch: {vars(ch)}")
            pk = ch.save()
            if not pk:
                return response.Response.package(error="Test could not be saved. Unknown error.")
            return response.Response.package(data=ch)
        
        @app.route('/modeltest/update', methods=('POST',))
        def modeltestupdate():
            kwargs = response.Response.unpackage(request.json)
            #log(f"kwargs: {kwargs}")
            ch = ModelTest(**kwargs)
            #log(f"ch: {vars(ch)}")
            pk = ch.save()
            if not pk:
                return response.Response.package(error="Test could not be saved. Unknown error.")
            return response.Response.package(data=ch)

        @app.route('/modeltest/delete', methods=('POST',))
        def modeltestdelete():
            pk = response.Response.unpackage(request.json)
            mt = ModelTest.get(pk)
            mt.delete()
            return response.Response.package(data=mt)

        return app
