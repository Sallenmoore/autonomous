from autonomous.tasks import make_taskrunner
from flask import Flask
from celery import Celery
import os


class Config:
    APP_NAME = __name__
    HOST = "0.0.0.0"
    PORT = 80
    SECRET_KEY = "TESTING"
    DEBUG = True
    TESTING = True
    TRAP_HTTP_EXCEPTIONS = True

    CELERY = dict(
        broker_url="pyamqp://user:bitnami@localhost",
        backend="rpc://user:bitnami@localhost",
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        track_started=True,
        store_errors_even_if_ignored=True,
    )


def test_create_task():
    app = Flask(__name__)
    app.config.from_object(Config())
    results = make_taskrunner(app)
    assert isinstance(results, Celery)
