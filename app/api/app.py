#local modules
import filters
from sharedlib.logger import log

#external Modules
import pytest
import pdoc
from flask import Flask, render_template

# Built-In Modules

import os
from pathlib import Path
import shutil
import logging 

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    #app.logger.disabled = True
    #logging.getLogger('werkzeug').disabled = True
    #set to 'config.Config' to use ENV_VARS
    #set to 'config.DevConfig' to use development settings
    #set to 'config.ProdConfig' to use production settings
    app.config.from_object('config.DevConfig') 

    #TODO: ensure the instance folder exists ???is this necessary?
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    with app.app_context():
        
        # Register our Routes
        from views import (compendium, dice, character,)
        
        app.register_blueprint(character.bp)
        app.register_blueprint(compendium.bp)
        app.register_blueprint(dice.bp)

        # Register the filters

        app.jinja_env.filters['markdown_to_html'] = filters.markdown_to_html
        
        @app.route('/', methods=('GET',))
        def index():

            modules=[
                'views.character',
                'views.compendium', 
                'views.dice', 
                'models.campaign.character',
                'models.campaign.dm',
                'models.campaign.event',
                'models.campaign.map',
                'models.compendium',
                'models.dice',
                'models.player',
                'sharedlib.db.db',
                'sharedlib.db.model',
                'sharedlib.model.APIModel',
            ]

            module_objects={'api':[], 'dev':[]}
            for mod in modules:
                mod_obj = pdoc.doc.Module.from_name(mod)
                mod_obj.menu_id = mod_obj.fullname.replace('', '').replace('.', '_')

                if mod_obj.fullname.startswith('views.'):
                    for endpoint in mod_obj.functions:
                        endpoint.api_endpoint_url = f"{mod_obj.name}/{endpoint.name}/"
                    module_objects['api'].append(mod_obj)
                else:
                    mod_obj.docstring = pdoc.render.to_html(mod_obj.docstring)
                    for obj in mod_obj.classes:
                        obj.classmethods = list(filter(lambda x: not x.name.startswith('__'), obj.classmethods))
                        obj.methods = list(filter(lambda x: not x.name.startswith('__'), obj.methods))
                        obj.class_variables = list(filter(lambda x: not x.name.startswith('__'), obj.class_variables))
                        obj.instance_variables = list(filter(lambda x: not x.name.startswith('__'), obj.instance_variables))
                    module_objects['dev'].append(mod_obj)

            context = {
                'home': pdoc.doc.Module.from_name('src').docstring,
                'docs': module_objects
            }
            return render_template("index.html", **context)

        #run the tests
        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-rxl --no-header -vv", "tests"])
            return {'results': f"{retcode}"}
        return app
#application factory
app = create_app()
