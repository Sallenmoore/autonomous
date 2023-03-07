# Built-In Modules

# external Modules
from flask import Blueprint, render_template, request, session
from autonomous import log

admin_page = Blueprint("admin", __name__)


@admin_page.route("/", methods=("GET",))
def index():
    if request.form:
        session.update(request.form)
    return render_template("index.html")


@admin_page.route("/add", methods=("POST",))
def add():
    return {"result": "success"}


@admin_page.route("/update", methods=("POST",))
def updates():
    return "updated"


@admin_page.route("/delete", methods=("POST",))
def delete():
    return "deleted"
