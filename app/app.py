# Required Imports
import os
from flask import Flask, g, session, request

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY")
    
    if test_config is not None:
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    ############## Setup Routes ###############
    from views import api, user, admin
    app.register_blueprint(api.bp, url_prefix="/api")
    app.register_blueprint(user.bp, url_prefix="/")
    app.register_blueprint(admin.bp, url_prefix="/admin")

    ############## Initializations ###############

    @app.before_request
    def before_request():
        app.logger.debug(f'\n\t== request url: {request.url}\n')

    return app