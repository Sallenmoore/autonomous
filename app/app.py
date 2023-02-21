import os

import firebase_admin
from config import DevelopmentConfig
from firebase_admin import db
from flask import Flask, render_template, request, session

# from models import Model
from utils import assets, log

# from webassets.filter import register_filter
# from webassets.filter.sass import DartSass


def create_app():
    app = Flask(os.getenv("APP_NAME", __name__))
    app.config.from_object(DevelopmentConfig)

    #################################################################
    #                             Extensions                        #
    #################################################################

    app.before_first_request(lambda: assets.build_assets())

    #################################################################
    #                             ROUTES                            #
    #################################################################

    @app.route("/", methods=["GET", "POST"])
    def index():
        log(ref.get())
        if request.form:
            session.update(request.form)
            log(request.form)
        ref.push({"testing": 123})
        return render_template("index.html")

    return app
