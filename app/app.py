import os

from config import DevelopmentConfig
from flask import Flask, render_template, request, session
from models import Model
from utils import log


def create_app():
    app = Flask(os.getenv("APP_NAME", __name__))
    app.config.from_object(DevelopmentConfig)
    #################################################################
    #                             Extensions                        #
    #################################################################

    #################################################################
    #                             ROUTES                            #
    #################################################################
    @app.route("/", methods=["GET", "POST"])
    def index():

        return render_template("index.html")

    return app
