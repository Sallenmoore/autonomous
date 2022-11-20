from autonomous.logger import log
from autonomous.response import Response
from autonomous import create_app
from models.modeltest import ModelTest
# application factory
app = create_app()

with app.app_context():

    @app.route('/modeltest/<int:pk>', methods=('GET',))
    def modeltestget(pk):
        mt = ModelTest.get(pk)
        #log(f"modeltestget: {mt}")
        return Response.package(data=mt)

    @app.route('/modeltest/all', methods=('GET',))
    def modeltestall():
        mt = ModelTest.all()
        return Response.package(data=mt)

    @app.route('/modeltest/search/', methods=('GET',))
    def modeltestsearch():
        mt = ModelTest.search(**request.values)
        return Response.package(data=mt)

    @app.route('/modeltest/create', methods=('POST',))
    def modeltestcreate():
        kwargs = Response.unpackage(request.json)
        #log(f"kwargs: {kwargs}")
        ch = ModelTest(**kwargs)
        #log(f"ch: {vars(ch)}")
        pk = ch.save()
        if not pk:
            return Response.package(error="Test could not be saved. Unknown error.")
        return Response.package(data=ch)
    
    @app.route('/modeltest/update', methods=('POST',))
    def modeltestupdate():
        kwargs = Response.unpackage(request.json)
        #log(f"kwargs: {kwargs}")
        ch = ModelTest(**kwargs)
        #log(f"ch: {vars(ch)}")
        pk = ch.save()
        if not pk:
            return Response.package(error="Test could not be saved. Unknown error.")
        return Response.package(data=ch)

    @app.route('/modeltest/delete', methods=('POST',))
    def modeltestdelete():
        pk = Response.unpackage(request.json)
        mt = ModelTest.get(pk)
        mt.delete()
        return Response.package(data=mt)
