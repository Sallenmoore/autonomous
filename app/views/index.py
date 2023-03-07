# Built-In Modules

# external Modules
from flask import Blueprint, render_template, request, session
from autonomous import log

index_page = Blueprint("", __name__)


@index_page.route("/", methods=("GET",))
def index():
    if request.form:
        session.update(request.form)
    return render_template("index.html")


@index_page.route("/add", methods=("POST",))
def add():
    return {"result": "success"}


@index_page.route("/update", methods=("POST",))
def updates():
    return "updated"


@index_page.route("/delete", methods=("POST",))
def delete():
    return "deleted"
