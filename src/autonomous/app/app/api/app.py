from autonomous import log
from autonomous import config, response
#from autonomous import create_app
from models.modeltest import ModelTest

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
        log(f"====================")

        @app.get('/')
        def index():
            return {"working": "it is"}
        
        @app.route('/modeltest/<int:pk>', methods=('GET',))
        def modeltestget(pk):
            mt = ModelTest.get(pk)
            #log(f"modeltestget: {mt}")
            return response.package(mt)

        @app.route('/modeltest/all', methods=('GET',))
        def modeltestall():
            mt = ModelTest.all()
            return response.package(mt)

        @app.route('/modeltest/search/', methods=('GET','POST'))
        def modeltestsearch():
            mt = ModelTest.search(**request.values)
            return response.package(mt)

        @app.route('/modeltest/update', methods=('POST',))
        @app.route('/modeltest/create', methods=('POST',))
        def modeltestupsert():
            log(f"request.json: {request.json}")
            
            models = response.unpackage(request.json)
            log(f"models: {models}")
            if not all(m.save() for m in models):
                return response.package("Test could not be saved. Unknown error.")
            return response.package(models)
        

        @app.route('/modeltest/delete', methods=('POST',))
        def modeltestdelete():
            pk = response.unpackage(request.json)
            mt = ModelTest.get(pk)
            mt.delete()
            return response.package(data=mt)

        # msg = "".join([f"{rule} => {rule.endpoint}\n" for rule in app.url_map.iter_rules()])
        # log(f"{msg}")
        # log(f"====================")
        return app
#application factory
app = create_app()