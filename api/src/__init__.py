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
        from src.models.item import Item
        from src.models.spell import Spell
        from src.models.monster import Monster
        from src.views import compendium, monster, item, spell, dice, base_search, base_random
        
        app.register_blueprint(compendium.bp)
        app.register_blueprint(monster.bp)
        app.register_blueprint(item.bp)
        app.register_blueprint(spell.bp)
        app.register_blueprint(dice.bp)

        @app.route('/', methods=('GET', 'POST'))
        def index():
            return {'Docs': {
                    "items": {
                            "random":{ "sample": base_random(Item)},
                            "search":{ "sample search: text=metal": base_search(Item, text="metal").get('results').pop()},
                            "all":{ 
                                "description":"Only the first result is shown",
                                "sample": base_search(Item).get('results').pop()
                                },
                        },
                    "spells": {
                            "random":{ "sample": base_random(Spell)},
                            "search":{ "sample search: text=ice": base_search(Spell, text="ice").get('results').pop()},
                            "all":{ 
                                "description":"Only the first result is shown",
                                "sample": base_search(Spell).get('results').pop()
                                },
                        },
                    "monster": {
                            "random":{ "sample": base_random(Monster)},
                            "search":{ "sample search: text=fire": base_search(Monster, text="fire").get('results').pop()},
                            "all":{ 
                                "description":"Only the first result is shown",
                                "sample": base_search(Monster).get('results').pop()
                                },
                        },
                }
            }

        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-rxl --no-header -vv", "tests"])
            return {'results': f"{retcode}"}
        
        return app