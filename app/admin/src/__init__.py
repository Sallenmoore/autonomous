
# Required Imports
import os
import pytest
from flask import Flask, render_template, request, redirect, url_for
import sass
import requests
import json
import logging

logging.basicConfig(level=logging.INFO, format="==%(levelname)s== [%(filename)s - %(funcName)s:%(lineno)d] --\n %(message)s")

def create_app(test_config=None):
    app = Flask(__name__)
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

        ################################################################
        ####                       Base Routes                       ###
        ################################################################
        
        # Include our Routes
        @app.route('/', methods=('GET', 'POST'))
        def index():
            context = {'classes': requests.get("http://api:8000/compendium/classes_list").json().get('results')}
            context['characters']= requests.get("http://api:8000/character/all").json().get('results')
            context['num_characters']= len(context['characters'])
            app.logger.debug(f"{context['characters']}")
            return render_template("index.html", **context)

        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-ral", "tests"])
            return {'results': retcode}

        ################################################################
        ####                      Character API                      ###
        ################################################################
        
        def character_api(endpoint, data):
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            app.logger.debug(f"{data} ===> {endpoint}")
            response = requests.post(f"http://api:8000/character/{endpoint}", data=data, headers=headers)
            app.logger.debug(f"{response}")
            return redirect(url_for('index'))

        @app.route('/create_character', methods=('GET', 'POST'))
        def create_character():
            return character_api('create', json.dumps(request.form))

        @app.route('/delete_character', methods=('POST',))
        def delete_character():
            app.logger.debug(request.form)
            return character_api('delete', json.dumps(request.form))

        @app.route('/update_character', methods=('GET', 'POST'))
        def update_character():
            return character_api('update', json.dumps(request.form))

        ################################################################
        ####                      Campaign API                      ###
        ################################################################
        
        def campaign_api(endpoint, data):
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            requests.post(f"http://api:8000/campaign/{endpoint}", data=data, headers=headers)
            return redirect(url_for('index'))

        @app.route('/add_campaign', methods=('GET', 'POST'))
        def add_campaign():
            return character_api('add', json.dumps(request.form))

        @app.route('/delete_campaign', methods=('GET', 'POST'))
        def delete_campaign():
            return character_api('delete', json.dumps(request.form))

        @app.route('/update_campaign', methods=('GET', 'POST'))
        def update_campaign():
            return character_api('update', json.dumps(request.form))

        ################################################################
        ###                       Compendium API                     ###
        ################################################################
        
        @app.route('/compendium', methods=('GET',))
        def compendium():
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            args = json.dumps(request.args)
            
            response = requests.post(f"http://api:8000/campaign/{args['endpoint']}", data=args['search'],headers=headers)
            return redirect(url_for('index'))

    return app