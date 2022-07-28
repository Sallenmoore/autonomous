# Required Imports
import os
import pytest
import logging
import pdoc
from flask import Flask

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
        @app.route('/', methods=('GET', 'POST'))
        def index():
            modules = ['src.views',]
            context = pdoc.Context()
            modules = [pdoc.Module(mod, context=context) for mod in modules]
            pdoc.link_inheritance(context)

            #local convenience function to get the documentation for a module
            def recursive_htmls(mod):
                yield mod.name, mod.html()
                for submod in mod.submodules():
                    yield from recursive_htmls(submod)
            docs = ""
            for mod in modules:
                for module_name, html in recursive_htmls(mod):
                    docs += html
                    
            return docs

        #run the tests
        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-rxl --no-header -vv", "tests"])
            return {'results': f"{retcode}"}
        
        return app