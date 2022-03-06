# Required Imports
import os
import random
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

        from api.views import compendium
        app.register_blueprint(compendium.bp)

        @app.route('/', methods=('GET', 'POST'))
        def index():
            return {'Docs': "TBD"}
        return app