from flask import Flask, request, render_template
import json 

app = Flask(__name__)

#API ROUTE
@app.route("/")
def index():
    return render_template('index.html')