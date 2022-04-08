# Required Imports
import os
import pytest
from flask import Flask

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY")
    app.config.from_object('config.Config')
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    with app.app_context():
        # Include our Routes

        from src.views import compendium, monster, item, spell, character, dice
        
        app.register_blueprint(compendium.bp)
        app.register_blueprint(monster.bp)
        app.register_blueprint(item.bp)
        app.register_blueprint(spell.bp)
        app.register_blueprint(character.bp)
        app.register_blueprint(dice.bp)

        @app.route('/', methods=('GET', 'POST'))
        def index():
            return {'Docs': {
                    "items": {
                        },
                    "spells": {
                        },
                    "monster": {
                        },
                }
            }

        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-x", "tests"])
            return {'results': f"{retcode}"}
        
        return app