from autonomous.logger import log
from autonomous import create_app
from autonomous.response import Response

from models.proxytest import ModelTest
from models.subproxytest import SubModelTest
# application factory

app = create_app()


with app.app_context():

    @app.route('/', methods=('GET',))
    def index():
        return {"working": "it is"}

    @app.route('/create', methods=('GET',))
    def create():
        result = ModelTest(
            name="test",
            status=SubModelTest(name="subtest"),
            collection=[1,2,3], 
            value = 754,
            nothing = None, 
            keystore = {'a':1, 'b':2},
            timestamp = datetime.now()
        ).save()
        
        return Response.package(data=result)

    @app.route('/read/<pk>:int', methods=('GET',))
    def read(pk):
        return Response.package(data=ModelTest.get(pk))
    
    @app.route('/update/<pk>:int', methods=('GET',))
    def update():
        data=ModelTest.get(pk)
        data.name = "updated"
        data.sub.name = "updated"
        data.save()
        return Response.package(data=ModelTest.get(pk))
    
    @app.route('/delete/<pk>:int', methods=('GET',))
    def delete():
        return Response.package(data=ModelTest.get(pk).delete())
    
    @app.route('/search/<term>', methods=('GET',))
    def search(term):
        return Response.package(data=ModelTest.search(term))
    
    @app.route('/all', methods=('GET',))
    def all():
        return Response.package(data=ModelTest.all())
