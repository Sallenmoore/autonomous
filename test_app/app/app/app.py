from autonomous.logger import log
from autonomous import config, response
#from autonomous import create_app
from models.proxytest import ModelTest

# External Modules
from flask import Flask, request

# Built-In Modules
import os

def make_model():
    m = ModelTest(
                name="test",
                status=SubModelTest(name="subtest", number=2),
                collection=[1,2,3], 
                value = 754,
                nothing = None, 
                keystore = {'a':1, 'b':2},
                timestamp = datetime.now()
            )
    m.save()
    return m


def create_app():
    app = Flask(os.getenv("APP_NAME", __name__))
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

        #log(f"view_functions: {app.view_functions}")
        
        @app.get('/create')
        def create():
            result = make_model()
            model = ModelTest.get(result.pk)
            assert result.name == model.name
            assert result.status == model.status
            assert result.collection == model.collection
            assert result.value == model.value
            assert result.keystore == model.keystore
            assert result.sub.subname == model.sub.name
            assert result.sub.number == model.sub.number
            return response.package(data=result)

        @app.get('/read')
        def read():
            make_model()
            for m in ModelTest.all():
                assert ModelTest.get(m.pk)
            return response.package(data=m)
        
        @app.get('/update')
        def update():
            make_model()
            data=ModelTest.all()[0]
            data.name = "updated"
            data.sub.name = "updated"
            data.save()
            data2=ModelTest.get(pk)
            assert data.name == data2.name == "updated"
            assert data.sub.name == data2.sub.name == "updated"
            return response.package(data=ModelTest.get(pk))
        
        @app.get('/delete')
        def delete():
            make_model()
            for m in ModelTest.all():
                ModelTest.get(m.pk).delete()
            assert not ModelTest.all()
            return response.package(data=[])
        
        @app.get('/search/')
        def search(term):
            make_model()
            assert ModelTest.search(name="test")
            return {}
        
        @app.get('/all')
        def all():
            make_model()
            assert ModelTest.all()
            return response.package(data=ModelTest.all())

        #msg = "".join([f"{rule}: {rule.endpoint}\n" for rule in app.url_map.iter_rules()])
        #log(f"{msg}")
        return app