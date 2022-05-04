
# Required Imports
import os
import pytest
from flask import Flask, render_template, request, redirect, url_for
import sass
import requests
import json


def create_app(test_config=None):
    app = Flask(__name__)
    FORMAT = '%(asctime)s %(clientip)-15s %(user)-8s %(message)s'
    app.logger.setLevel("DEBUG")
    app.config.from_pyfile('../config.py')
    app.secret_key = os.environ.get("SECRET_KEY")
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    if os.environ.get("ENV") == 'development':
        @app.before_request
        def before_request_tasks():
            sass.compile(dirname=('static/style/sass', 'static/style'), output_style='nested')

    with app.app_context():
        
        # Include our Routes
        @app.route('/', methods=('GET', 'POST'))
        def index():
            context = {'classes': requests.get("http://api:8000/compendium/classes_list").json().get('results')}
            context['characters']= requests.get("http://api:8000/character/all").json().get('results')
            return render_template("index.html", **context)

        @app.route('/add_character', methods=('GET', 'POST'))
        def add_character():
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            requests.post("http://api:8000/character/create", data=json.dumps(request.form), headers=headers)
            return redirect(url_for('admin'))

            
        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-ral", "tests"])
            return {'results': retcode}

    return app