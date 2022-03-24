# Required Imports
import os

from flask import Flask, render_template
import sass
from src.models.monster import Monster

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_pyfile('../config.py')
    app.secret_key = os.environ.get("SECRET_KEY")
    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    @app.before_request
    def before_request_tasks():
        sass.compile(dirname=('static/style/sass', 'static/style'), output_style='nested')

    with app.app_context():
        # Include our Routes
        @app.route('/', methods=('GET', 'POST'))
        def index():
            random_monster = Monster.random()
            app.logger.info(f"monster: {[vars(a) for a in random_monster.actions]}")
            return render_template("index.html", 
                                   random_monster = random_monster,
                                   dice_types = [4,6,8,10,12,20,100],
                                   )

    return app