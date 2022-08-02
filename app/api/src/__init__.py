"""
# DM Buddy

DnD Helper Application

## Container Apps

DM Buddy has 4 inital container components:

* **server**
    * static files and assets are served from here. This is also the main entry point for the application.
* **api**
    * The backend API and database
    * currently implented with Flask and TinyDB
* **admin**
    * An admin web interface
* **view**
    * The front end interface
  
---

## Stack Documentation

### Docker

* [Docker](https://docs.docker.com/)
* [Docker Compose](https://github.com/compose-spec/compose-spec/blob/master/spec.md)

### Server

* [nginx](https://docs.nginx.com/nginx/)
* [gunicorn](https://docs.gunicorn.org/en/stable/configure.html)

### Backend Stack

* [Python](https://docs.python.org/3.9/)
* [Flask](https://flask.palletsprojects.com/en/2.1.x/)

### Frontend Stack

* [Materialize](https://materializecss.com/select.html)
* [JQuery](https://api.jquery.com/)

### Database

* [TinyDB](https://tinydb.readthedocs.io/en/latest/usage.html)

### Testing

* [pytest](https://docs.pytest.org/en/7.1.x/reference/reference.html)
* [coverage](https://coverage.readthedocs.io/en/6.4.1/cmd.html)
"""

#external Modules
import pytest
import pdoc
from flask import Flask, render_template

# Built-In Modules
import os
from pathlib import Path
import logging
import shutil

logging.basicConfig(level=logging.INFO, format="==%(levelname)s== [%(filename)s - %(funcName)s:%(lineno)d] --\n %(message)s")
log = logging.getLogger()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    
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
        
        # Include our Routes
        from src.views import (compendium, monster, item, spell, dice, character,)
        
        app.register_blueprint(character.bp)
        app.register_blueprint(compendium.bp)
        app.register_blueprint(monster.bp)
        app.register_blueprint(item.bp)
        app.register_blueprint(spell.bp)
        app.register_blueprint(dice.bp)

        #TODO figure out how to generate documentation
        @app.route('/', methods=('GET',))
        def index():

            modules=[
                'src.views.character',
                'src.views.compendium', 
                'src.views.monster', 
                'src.views.item',
                'src.views.spell',
                'src.views.dice', 
                'src.models.campaign.character',
                'src.models.campaign.dm',
                'src.models.campaign.event',
                'src.models.campaign.map',
                'src.models.campaign.monster',
                'src.models.campaign.npc',
                'src.models.compendium',
                'src.models.compendium.item',
                'src.models.compendium.api',
                'src.models.compendium.spell',
                'src.models.dice',
                'src.models.player',
            ]

            module_objects={'api':[], 'dev':[]}
            for mod in modules:
                mod_obj = pdoc.doc.Module.from_name(mod)
                mod_obj.fullname = mod_obj.fullname.removeprefix('src.')
                mod_obj.menu_id = mod_obj.fullname.replace('.', '_')

                if mod_obj.fullname.startswith('models.'):
                    for obj in mod_obj.classes:
                        obj.classmethods = list(filter(lambda x: not x.name.startswith('__'), obj.classmethods))
                        obj.methods = list(filter(lambda x: not x.name.startswith('__'), obj.methods))
                        obj.class_variables = list(filter(lambda x: not x.name.startswith('__'), obj.class_variables))
                        obj.instance_variables = list(filter(lambda x: not x.name.startswith('__'), obj.instance_variables))
                    module_objects['dev'].append(mod_obj)
                elif mod_obj.fullname.startswith('views.'):
                    for endpoint in mod_obj.functions:
                        endpoint.api_endpoint_url = f"{mod_obj.name}/{endpoint.name}/"
                    module_objects['api'].append(mod_obj)

            context = {
                'docs': module_objects
            }
            
            return render_template("index.html", **context)

        #run the tests
        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-rxl --no-header -vv", "tests"])
            return {'results': f"{retcode}"}
        
        return app