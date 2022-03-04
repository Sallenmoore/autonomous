# Required Imports
import os
import random
from flask import Flask, request

app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

# ensure the instance folder exists
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

from models import Compendium

@app.route('/', methods=('GET', 'POST'))
def index():
    return {
        'calls-available': {
            'task': {
                'random_monster':{
                    "METHODS":"GET",
                    "DESCRIPTION": "returns a random monster object",
                    "return format": "TBD"
                    }, 
                }
            }
        }

@app.route('/random_monster', methods=('GET',))
def random_monster():
    results = Compendium.search_monsters()
    return random.choice(results['results'])