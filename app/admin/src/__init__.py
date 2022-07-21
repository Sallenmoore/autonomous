
from src.models import Compendium, Character
# Required Imports
import os
import pytest
from flask import Flask, render_template, request, redirect, url_for, session
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
            #campaign = Campaign(session.get('campaign_id'))
            context = {'classes': Compendium.AVAILABLE_CLASSES, 'characters': Character.all()}
            return render_template("index.html", **context)

        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-ral", "tests"])
            return {'results': retcode}

        ################################################################
        ####                      Character API                      ###
        ################################################################

        @app.route('/create_character', methods=('POST',))
        def create_character():
            result = Character.save(request.form)
            return redirect(url_for("index"))

        @app.route('/character/<pk>', methods=('GET', 'POST'))
        def get_character(pk):
            result = Character.get(request.form)
            return redirect(url_for("index"))

        @app.route('/update_character', methods=('GET', 'POST'))
        def update_character():
            result = Character.save(request.form)
            return redirect(url_for("index"))

        @app.route('/delete_character', methods=('POST',))
        def delete_character():
            result = Character.delete(request.form)
            return redirect(url_for("index"))

        ################################################################
        ####                      Campaign API                      ###
        ################################################################
        
        # def campaign_api(endpoint, data):
        #     headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        #     requests.post(f"http://api:8000/campaign/{endpoint}", data=data, headers=headers)
        #     return redirect(url_for('index'))

        # @app.route('/add_campaign', methods=('GET', 'POST'))
        # def add_campaign():
        #     return character_api('add', json.dumps(request.form))

        # @app.route('/delete_campaign', methods=('GET', 'POST'))
        # def delete_campaign():
        #     return character_api('delete', json.dumps(request.form))

        # @app.route('/update_campaign', methods=('GET', 'POST'))
        # def update_campaign():
        #     return character_api('update', json.dumps(request.form))

        ################################################################
        ###                       Compendium API                     ###
        ################################################################
        
        @app.route('/compendium', methods=('GET',))
        def compendium():
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            args = json.dumps(request.args)

            url -= f"http://api:8000/compendium/"
            response = requests.get(url, headers=headers)
            return response.json()

            response = requests.post(f"http://api:8000/compendium/{args['endpoint']}", data={'search':args['search']},headers=headers)
            return redirect(url_for('index'))

    ###### returns the application instance to the caller ######

    return app