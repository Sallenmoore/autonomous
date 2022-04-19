# Required Imports
import os
import pytest
from flask import Flask, render_template
import sass
from src.models.monster import Monster
from src.models.item import Item
from src.models.spell import Spell

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
        # Include our Routes
        @app.route('/', methods=('GET', 'POST'))
        def index():
            random_monster = Monster.random()
            random_item = Item.random()
            random_spell = Spell.random()
            return render_template("index.html", 
                                   random_monster = random_monster,
                                   dice_types = [4,6,8,10,12,20,100],
                                   random_item = random_item,
                                   random_spell = random_spell,
                                   )
            
        @app.route('/test', methods=('GET',))
        def test():
            retcode = pytest.main(["-ral", "tests"])
            return {'results': retcode}

    return app