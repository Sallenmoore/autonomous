
from models import Compendium, Character
# Required Imports
import os
import pytest
from flask import Flask, render_template, request, redirect, url_for, session
import sass
import requests
import json
import logging
from collections import defaultdict
import urllib.parse

logging.basicConfig(level=logging.INFO, format="==%(levelname)s== [%(filename)s - %(funcName)s:%(lineno)d] --\n %(message)s")
log = logging.getLogger()

def create_app(test_config=None):
    app = Flask(__name__)

    #set to 'config.Config' to use ENV_VARS
    #set to 'config.DevConfig' to use development settings
    #set to 'config.ProdConfig' to use production settings
    app.config.from_object('config.DevConfig') 
    
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
            characters = Character.all()

            # Update context wtih session data
            if session.get('compendium_search'):
                context['compendium_search_results'] = session['compendium_search']

            
            context = {
                'classes': [cl['name'] for cl in Compendium.get_classes()], 
                'characters': characters
            }
            return render_template("index.html", **context)

        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-ral", "tests"])
            return {'results': retcode}

        ################################################################
        ####                      Character API                      ###
        ################################################################

        @app.route('/character/create', methods=('POST',))
        def create_character():
            char = Character(**request.form)
            #logger.debug(f"Creating character: {char}")
            session['character_create'] = char.save()
            return redirect(url_for("index"))

        @app.route('/character/<pk>', methods=('GET', 'POST'))
        def get_character(pk):
            session['character_get']  = Character.get(**request.form)
            return redirect(url_for("index"))

        @app.route('/character/update', methods=('GET', 'POST'))
        def update_character():
            
            log.debug(request.form)

            character = Character(**request.form)

            log.info("===============   NO PK  =================")
            log.info(character)

            character.save()
            return redirect(url_for("index"))

        @app.route('/character/delete', methods=('POST',))
        def delete_character():
            session['character_delete'] = Character(**request.form).delete()
            return redirect(url_for("index"))

        @app.route('/character/activate', methods=('POST',))
        def activate_character():
            char_data = {
                "pk":request.form.get("pk"),
                "active" : True if request.form.get('activate') else False,
            }
            
            log.info(f'{request.form}')
            Character(**char_data).save()
            return redirect(url_for("index"))

        ################################################################
        ####                      Campaign API                      ###
        ################################################################
        
        # def campaign_api(endpoint, data):
        #     headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        #     requests.post(f"http://api:44666/campaign/{endpoint}", data=data, headers=headers)
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
        ###                       Compendium Search                     ###
        ################################################################
        
        @app.route('/compendium', methods=('POST',))
        def compendium():
            #log.info(f"search: {request.json.get('search_term')}, endpoint:{request.json.get('endpoint')}")
            results = Compendium.search(search=request.json.get('search_term'), endpoint=request.json.get('endpoint'))
            return results

    ###### returns the application instance to the caller ######

    return app

#application factory
app = create_app()
