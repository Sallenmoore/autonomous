import logging
import os
import random

from config import DevelopmentConfig
from flask import Flask, render_template, request, session
from models import Story
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
        # log(request.form)
        story = Story(prompt=request.form.get("dm", session.get("story")))
        story.next_chapter(update=request.form.get("party"))
        session["story"] = story.summary
        log(vars(story))
        return render_template("index.html", story=story)

    return app
