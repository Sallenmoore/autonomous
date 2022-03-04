# Required Imports
import os
from flask import Flask, request

app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
# ensure the instance folder exists
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

from models.monster import Monster

@app.route("/")
def index():
    return Monster.get_random_monster()